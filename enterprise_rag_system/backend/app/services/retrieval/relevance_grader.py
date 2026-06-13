from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.core.prompts import GRADE_PROMPT


def grade_documents(question: str, documents: list[str], llm) -> list[str]:
    chain = ChatPromptTemplate.from_template(GRADE_PROMPT) | llm | StrOutputParser()
    relevant = []
    for document in documents:
        result = chain.invoke({"document": document, "question": question})
        if "yes" in result.strip().lower():
            relevant.append(document)
    return relevant if relevant else documents

