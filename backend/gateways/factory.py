from backend.config import Settings, settings
from backend.gateways.contracts import KnowledgeGateway, LLMGateway
from backend.gateways.mocks import MockKnowledgeGateway, MockLLMGateway
from backend.gateways.qdrant_adapter import QdrantKnowledgeAdapter
from backend.gateways.real_llm import OpenAICompatibleLLMAdapter


def create_knowledge_gateway(config: Settings = settings) -> KnowledgeGateway:
    if config.knowledge_gateway_mode == "mock":
        return MockKnowledgeGateway()
    if config.knowledge_gateway_mode == "qdrant":
        return QdrantKnowledgeAdapter(config.qdrant_url, config.qdrant_api_key, config.qdrant_collection, config.qdrant_timeout)
    raise ValueError(f"Unsupported KNOWLEDGE_GATEWAY_MODE: {config.knowledge_gateway_mode}")


def create_llm_gateway(config: Settings = settings) -> LLMGateway:
    """Explicit gateway switch. `real` never falls back to Mock on failure."""
    if config.llm_gateway_mode == "mock":
        return MockLLMGateway()
    if config.llm_gateway_mode == "real":
        return OpenAICompatibleLLMAdapter(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key,
            model=config.llm_model,
            timeout=config.llm_timeout,
            temperature=config.llm_temperature,
            max_tokens=config.llm_max_tokens,
        )
    raise ValueError(f"Unsupported LLM_GATEWAY_MODE: {config.llm_gateway_mode}")
