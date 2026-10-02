# ADR-010：通过 Knowledge API Adapter 接入 Qdrant

状态：接受。

业务层继续依赖 `KnowledgeGateway`。真实实现 `QdrantKnowledgeAdapter` 调用负责 Embedding、混合检索和 Qdrant 访问的独立 Knowledge API，不让 Business API 直接依赖 Qdrant SDK 或本地模型。

