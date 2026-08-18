from synapse.ask import answer_question
from synapse.rag import AnswerResult, Question, RetrievedChunk, Source


def test_source_grounded_contract_types_preserve_public_answer_shape():
    question = Question(
        text="What algorithm does OSPF use?", filters={"source_path": "Notes/ospf.md"}
    )
    chunk = RetrievedChunk(
        score=0.91,
        payload={
            "title": "OSPF",
            "source_path": "Notes/ospf.md",
            "text": "OSPF uses Dijkstra's Shortest Path First algorithm.",
            "chunk_index": 0,
        },
    )
    source = Source.from_mapping(
        {**chunk.payload, "score": chunk.score, "quoted_support": chunk.payload["text"]}
    )
    result = AnswerResult(
        question=question.text,
        answer="OSPF uses Dijkstra's Shortest Path First algorithm. [1]",
        insufficient_context=False,
        sources=(source,),
        retrieval={"accepted": 1, "answer_validation": "quote_overlap"},
    )

    assert question.to_mapping() == {
        "question": "What algorithm does OSPF use?",
        "filters": {"source_path": "Notes/ospf.md"},
        "exact_run_id": "",
    }
    assert chunk.to_point()["payload"]["source_path"] == "Notes/ospf.md"
    assert result.to_dict()["sources"][0]["source_path"] == "Notes/ospf.md"
    assert result.to_dict()["retrieval"]["answer_validation"] == "quote_overlap"


def test_source_grounded_contract_orchestrates_retriever_generator_and_validator():
    question = Question(text="What algorithm does OSPF use?")
    seen = {}

    class Retriever:
        def retrieve(self, received):
            seen["question"] = received
            return [
                RetrievedChunk(
                    score=0.9,
                    payload={
                        "title": "OSPF",
                        "source_path": "Notes/ospf.md",
                        "text": "OSPF uses Dijkstra's Shortest Path First algorithm.",
                        "chunk_index": 0,
                    },
                )
            ]

    class Generator:
        def generate(self, received, context, sources):
            seen["context"] = context
            seen["sources"] = sources
            return "OSPF uses Dijkstra's Shortest Path First algorithm. [1]"

    class Validator:
        def validate(
            self, received, answer, sources, retrieval, *, insufficient_context=False
        ):
            return AnswerResult(
                question=received.text,
                answer=answer,
                insufficient_context=insufficient_context,
                sources=tuple(sources),
                retrieval=retrieval,
            )

    result = answer_question(
        question,
        Retriever(),
        Generator(),
        Validator(),
        env={"RAG_SCORE_THRESHOLD": "0"},
    )

    assert result.answer.endswith("[1]")
    assert result.sources[0].source_path == "Notes/ospf.md"
    assert seen["question"] is question
    assert "Dijkstra" in seen["context"]
    assert len(seen["sources"]) == 1
