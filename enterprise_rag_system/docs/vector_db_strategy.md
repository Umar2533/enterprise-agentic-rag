# Vector DB Strategy

The project currently uses Qdrant through `QdrantVectorDB`.

The application talks to vector stores through `VectorDB.build_retriever()`. To
add another provider, create a new service file and update the factory.

