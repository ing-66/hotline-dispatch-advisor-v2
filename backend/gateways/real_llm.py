"""Real LLM adapter for OpenAI-compatible chat/completions providers.

The adapter lives entirely in the Gateway layer. `AnalysisService` only depends
on the `LLMGateway` contract, so providers (DeepSeek, OpenAI, compatible local
endpoints) can be switched without touching business logic.

The model only sees the Evidence Pack produced from `KnowledgeGateway.search`
and is required to reference evidence ids from that pack. It never sees Qdrant
or Knowledge API raw structures.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

import httpx

from backend.gateways.contracts import AnalysisResult, LLMGateway, RetrievalResult


class LLMGatewayError(RuntimeError):
    """Base error for real LLM gateway failures."""


class LLMConfigurationError(LLMGatewayError):
    pass


class LLMQuotaError(LLMGatewayError):
    """Provider account quota / billing issue (HTTP 402)."""


class LLMAuthenticationError(LLMGatewayError):
    pass


class LLMModelNotFoundError(LLMGatewayError):
    pass


class LLMRateLimitError(LLMGatewayError):
    pass


class LLMConnectionError(LLMGatewayError):
    pass


class LLMTimeoutError(LLMGatewayError):
    pass


class LLMServerError(LLMGatewayError):
    pass


class LLMResponseError(LLMGatewayError):
    pass


class LLMValidationError(LLMGatewayError):
    pass


SYSTEM_PROMPT = """你是广州市白云区12345热线工单智能研判助手。你的答案供派单人员直接使用，
目标是给出可执行、可追溯且不过度推断的派单建议，而不是复述检索材料。

一、案件辖区与知识层级
1. case_jurisdiction（案件业务辖区）与 knowledge_scope（知识适用层级）是两回事。
2. 本系统默认服务广州市白云区。工单正文没有写区名时，默认案件辖区就是
   广州市白云区；不得因为正文没出现“白云区”而认定行政区域未知。
3. 正文明确出现天河区/越秀区/番禺区等其它广州区，或深圳/佛山等外市时，
   案件属于非白云区，超出当前系统默认业务辖区：不要强行推荐白云区部门；
   recommended_department 写“转派至事项所在地12345热线/属地区级承办体系”，并在结论中
   写明已识别的所在地；若跨区事实明确，confidence 表示“转派判断”的可信度，可为 0.8~1.0，
   不得因为本系统不负责就机械写成 0。
4. 不知道具体镇街 ≠ 无法研判。可输出“属地街道办事处/属地镇人民政府”，
   在风险提示中说明需结合具体地址确认实际镇街。

二、知识使用规则
1. 国家、广东省、广州市、白云区知识都可以作为白云区工单的依据：
   上位知识用于确定职责体系，区级知识用于落到白云区具体承办主体，
   历史案例用于业务经验参考。
2. 广州市文件依法适用于广州市行政区域，对白云区事项同样有效；
   不得把“广州市文件”当成“不是白云区依据”而排除。
3. 引用只能使用每个证据块开头方括号中的完整 evidence_id
   （形如 department_duties:123 或 historical_cases:456），正文里出现的
   “证据ID：E1/E2”只是原文残留标记，不是可用引用键；不得引用不存在的 evidence_id。
4. citation_references 中每一个 ID，都必须在 evidence 数组中提供一项可逐字校验的 quote；
   recommended_department、competent_authority、collaborating_units 中每个单位至少要有一条职责证据，
   历史案例只允许支持 recommended_department 的“曾受理经验”，不能单独证明业务主管单位。
5. “直接职责依据”必须同时满足事项行为、适用对象和职责结论三者匹配。只命中单位名、工单类型标签
   （如“投诉、咨询、建议、举报”）或其它特定对象的相似条款，不得作为本案直接职责依据；例如
   “托幼机构擅设卫生室”的条款不能直接证明出租屋牙科诊所的处罚职责。此类材料只能用于辅助研判。

三、研判策略
1. 先识别事项类型，再按“职责体系 → 具体承办主体 → 历史经验”综合研判。
2. 允许基于多条真实证据做合理综合，不要求某条法规逐字覆盖当前情形。
3. 有真实证据形成候选时，允许给出低置信度建议（confidence 0.3~0.7），
   例如第一建议“属地街道办事处/镇人民政府”，第二建议“白云区住房建设和交通局”。
4. “依据不足，建议人工复核”是最后手段，仅当无法识别事项类型且无法形成任何候选时使用；
   明确超出辖区时应给出转派建议，不属于依据不足。能识别事项类型但缺少地址、权属或噪声来源时，
   应给出条件化候选并明确需要补充的最少信息，confidence 通常为 0.3~0.6。
5. 不得编造政策、法规、案例或部门职责；不得生成 Evidence Pack 以外的依据。

四、主办、协办与紧急事项
1. recommended_department 必须短、明确、可派单，并且只能写一个“建议首派”单位名称；
   禁止在此字段写“主办：X；协办：Y”。业务主管只写 competent_authority，协同单位只写
   collaborating_units，不得在三个字段间重复同一单位。
2. 对复合诉求逐项判断职责，再指定最适合统筹的主办单位；协办单位只在确有必要时列出。
3. 对困人、燃气泄漏、火灾、坍塌、触电、严重积水等正在发生的人身安全事件，先说明立即报警、
   应急救援或通知专业救援单位，再说明后续行政派单。recommended_department 仍只写行政首派单位，
   紧急救援动作必须放在 risk_warning 第一处，监管单位放 competent_authority；不得把日常协调单位
   描述成专业救援主体。
4. 区分直接责任、行政监管和协调责任。例如物业或设施权属单位可能承担直接处置责任，
   镇街负责协调不等于镇街承担专业维修或执法责任。证据未确认具体主体身份时必须使用条件句。
5. 电梯场景写“电梯使用管理人（通常为物业，具体以登记为准）”，不得未经核实直接断言物业
   就是法定使用管理人；维保单位负责专业救援和故障处置，不等于对事故原因当然负全部责任。

五、承办建议粒度与事实约束
1. 只能输出“当前工单事实能支持的最高确定性建议”：
   - 工单明确某镇街 → 才输出该镇街具体名称；
   - 工单只明确白云区、未明确镇街 → 只能输出“属地街道办事处/属地镇人民政府”，
     不得从证据/历史案例中挑一个具体镇街；
   - 只能判断责任体系但设施权属不明 → 可输出“属地镇街/对应设施养护责任单位”，
     并在 risk_warning 中说明需核实道路/设施权属；
   - 不知道具体道路/地址/产权，不属于“依据不足”；应输出候选层级并给
     confidence 0.4~0.6。
2. 只有完全无法识别事项性质、或没有任何有效证据时，才允许
   “依据不足，建议人工复核”（confidence=0）。
3. 工单明确写出镇街时，recommended_department 必须使用该镇街的具体名称；不得一边写具体镇街，
   一边在其它字段声称镇街未知。比如正文写“棠景街”，建议栏应写“棠景街道办事处”，不得仍写
   “属地街道办事处/属地镇人民政府”；正文写“钟落潭镇”，应写“钟落潭镇人民政府”。
   只写“白云区某小区”不等于写明镇街。
4. 严格区分“工单明示事实”“基于事实的判断”“需要核实的条件”。不得把“睡不着”直接写成已确认的
   某一种噪声来源，不得把“楼下”自动补成餐饮、施工或娱乐场所。

六、历史案例不得传播个案事实
1. Evidence（含历史案例）只用于判断职责类型、承办层级、处理模式、部门协同；
   不得把 Evidence 中的具体镇街/道路/小区/企业/地址当成本案事实。
2. 历史案例中出现“棠景街”不等于本单在棠景街；当前工单未写镇街时，
   禁止输出任何历史案例中的具体镇街名称。
3. 同类历史案例只能支持“此类事项历史上由属地街道承办”的职责层级推断。

七、表达质量
1. conclusion 按“事项识别—职责判断—派单结论”的逻辑自然成段，通常控制在 120~260 字；
   不要真的输出“事项识别：”“职责判断：”“派单结论：”这些机械标签，不逐条复述法规，
   不在正文显示 department_duties:123 等内部 evidence_id。
2. responsibility_boundary 只写直接责任主体、主办单位、协办/监管单位之间的边界；未知事项用条件句。
3. risk_warning 只写会影响派单或处置的风险、需核实信息和紧迫措施，不重复结论。
   工单未明确出现诈骗、恶意侵占、人员聚集、冲突威胁等线索时，不得泛化提示报警、诈骗、维稳、
   群体性事件或情绪激动；不得凭空增加与派单无关的核实项。
4. confidence 衡量本次“派单/转派建议”的可信度：事实和直接职责证据充分为 0.75~0.95；
   有合理候选但缺地址、权属、来源等关键事实为 0.35~0.65；完全无法形成候选才为 0。
5. 输出前执行一致性自检：辖区、镇街、事项类型、主办单位、责任边界、风险提示和 confidence
   不得互相矛盾；任何未由工单或 Evidence Pack 支持的专名都必须删除或改为条件表达。
   competent_authority 只能是纯单位名称，条件和权属说明放入 missing_facts，不得写
   “某某局（如设施已移交）”；主管暂不能确定时输出空字符串。
6. 正文每点名一部法律、法规、文件或某部门的具体法定职责，citation_references 中必须包含一条
   标题或原文明示该名称/职责的证据。若 Evidence Pack 只有一般性证据，就改写为一般职责判断，
   不得调用模型记忆补充《居民身份证法》《网络安全法》等未被本次证据支持的名称。
7. 不使用“维稳”等泛化表述。镇街协办应具体写成现场联系、地址核实、矛盾协调或督促整改。
8. 投诉中的“怀疑、可能、疑似、听说”不等于已确认事实；全文保持“需核查/涉嫌/如查实”的条件性，
   不得在责任边界中把被投诉对象直接定性为违法责任人。

八、个人信息泄露专项规则
1. 先识别谁控制或持有数据。政务大厅、学校、医院、企业等场景中，涉事单位及其主管单位应先
   删除或阻断传播、保存日志、核查泄露范围、联系接收者删除，并按规定告知和整改。
2. 不得仅因出现身份证照片、手机号码或微信群就断定构成犯罪、直接把公安机关列为唯一主办。
   只有 Evidence Pack 明确支持公安管辖，或工单存在买卖信息、诈骗、恶意传播等违法犯罪线索时，
   才可将公安列为主办或协办；否则写成“如发现违法犯罪线索，移交公安机关”。
3. 网信、数据管理、公安、市场监管等单位的介入必须分别说明触发条件，不能无依据全部罗列。
4. 政务大厅具体名称及其主管单位不明时，recommended_department 写“主办：涉事政务办事大厅
   主管单位；如发现违法犯罪线索，移交公安机关”，不得猜测或新造某个数据管理局、政务服务局。
   只有 Evidence Pack 明确给出该大厅与主管单位的对应关系时，才可输出具体主管单位名称。
5. 未查明由谁转发前，直接责任主体只能写“涉事信息处理单位应先行处置；具体泄露责任人待调查”，
   禁止写“直接责任主体为涉事大厅及其工作人员”或同义表述，不得直接认定大厅工作人员违法，
   也不得把公安写成无条件协办单位。

九、输出
只输出一个 JSON 对象，不要输出 Markdown 代码块或额外解释：
{
  "recommended_department": "建议首派单位",
  "competent_authority": "业务主管单位；无直接证据时为空字符串",
  "collaborating_units": ["有直接证据支持的协同单位"],
  "decision_status": "supported、needs_fact_check、multi_agency 三选一",
  "missing_facts": ["影响派单的待核实条件；没有则为空数组"],
  "evidence": [
    {"evidence_id": "Evidence Pack 内真实 evidence_id", "claim": "该证据直接支持的结论", "quote": "证据原文中的逐字短句"}
  ],
  "conclusion": "简洁研判说明",
  "citation_references": ["Evidence Pack 内真实 evidence_id"],
  "responsibility_boundary": "责任边界（可空）",
  "confidence": 0.55,
  "risk_warning": "风险提示（可空）"
}"""


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.S)
    if match:
        return match.group(1).strip()
    return text


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = _strip_code_fence(text)
    try:
        value = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise LLMResponseError("model returned no JSON object")
        try:
            value = json.loads(cleaned[start : end + 1])
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMResponseError(f"model returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise LLMResponseError("model returned a non-object JSON value")
    return value


class OpenAICompatibleLLMAdapter(LLMGateway):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 240.0,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = client
        self.provider = "deepseek" if "deepseek" in self.base_url else "openai-compatible"
        self.model_name = model

    @staticmethod
    def _build_evidence_pack(evidence: list[RetrievalResult]) -> str:
        blocks = []
        for item in evidence:
            metadata = item.metadata or {}
            extra = []
            if metadata.get("source_type"):
                extra.append(f"类型={metadata['source_type']}")
            if metadata.get("source_case_id"):
                extra.append(f"历史工单号={metadata['source_case_id']}")
            elif metadata.get("case_id"):
                extra.append(f"历史工单号={metadata['case_id']}")
            content = item.content
            content = re.sub(r"【证据ID：\s*E\d+\s*】\s*", "", content)
            content = re.sub(r"【文件名：[^】]*】\s*", "", content)
            blocks.append(
                f"[{item.evidence_id}] "
                f"{'（' + '，'.join(extra) + '）' if extra else ''}\n"
                f"标题：{item.document_title or item.metadata.get('source_title') or item.knowledge_base_id}\n"
                f"原文：{content}"
            )
        return "\n\n".join(blocks) if blocks else "（本次未召回任何可用证据）"

    def _chat(self, messages: list[dict[str, str]], _retry: int = 0) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        client = self._client or httpx.Client(timeout=self.timeout)
        close = self._client is None
        try:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        except httpx.TimeoutException as exc:
            if _retry < 1:
                return self._chat(messages, _retry=1)
            raise LLMTimeoutError("LLM request timed out") from exc
        except httpx.HTTPError as exc:
            if _retry < 1:
                return self._chat(messages, _retry=1)
            raise LLMConnectionError(f"LLM request failed: {exc}") from exc
        finally:
            if close:
                client.close()

        if response.status_code in (401, 403):
            raise LLMAuthenticationError("LLM API authentication failed (check LLM_API_KEY)")
        if response.status_code == 402:
            raise LLMQuotaError("LLM provider reported insufficient quota/balance (402)")
        if response.status_code == 404:
            raise LLMModelNotFoundError(f"LLM model not found: {self.model}")
        if response.status_code == 429:
            if _retry < 1:
                return self._chat(messages, _retry=1)
            raise LLMRateLimitError("LLM rate limited (429)")
        if response.status_code >= 500:
            if _retry < 1:
                return self._chat(messages, _retry=1)
            raise LLMServerError(f"LLM provider server error ({response.status_code})")
        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMResponseError("LLM provider returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise LLMResponseError("LLM provider returned a non-object payload")
        choices = payload.get("choices") or []
        content = ""
        if choices:
            message = choices[0].get("message") or {}
            content = str(message.get("content") or "")
        if not content.strip():
            if _retry < 1:
                return self._chat(messages, _retry=1)
            raise LLMResponseError("LLM returned empty content")
        return content

    def _chat_stream(self, messages: list[dict[str, str]]):
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        client = self._client or httpx.Client(timeout=self.timeout)
        close = self._client is None
        try:
            with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=body,
            ) as response:
                if response.status_code in (401, 403):
                    raise LLMAuthenticationError("LLM API authentication failed (check LLM_API_KEY)")
                if response.status_code == 404:
                    raise LLMModelNotFoundError(f"LLM model not found: {self.model}")
                if response.status_code == 429:
                    raise LLMRateLimitError("LLM rate limited (429)")
                if response.status_code >= 500:
                    raise LLMServerError(f"LLM provider server error ({response.status_code})")
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        payload = json.loads(data)
                        choices = payload.get("choices") or []
                        delta = (choices[0].get("delta") or {}).get("content") if choices else None
                    except (ValueError, TypeError, AttributeError):
                        continue
                    if delta:
                        yield str(delta)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("LLM request timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMConnectionError(f"LLM request failed: {exc}") from exc
        finally:
            if close:
                client.close()

    @staticmethod
    def _validate(obj: dict[str, Any], evidence_by_id: dict[str, RetrievalResult]) -> AnalysisResult:
        required = ("recommended_department", "conclusion", "citation_references")
        missing = [key for key in required if key not in obj]
        if missing:
            raise LLMValidationError(f"LLM output missing required fields: {missing}")

        department = obj["recommended_department"]
        conclusion = obj["conclusion"]
        refs = obj["citation_references"]
        if not isinstance(department, str) or not isinstance(conclusion, str):
            raise LLMValidationError("recommended_department/conclusion must be strings")
        if not isinstance(refs, list) or not all(isinstance(x, str) for x in refs):
            raise LLMValidationError("citation_references must be a list of strings")

        unknown = sorted(set(refs) - evidence_by_id.keys())
        if unknown:
            raise LLMValidationError(f"LLM referenced unknown evidence ids: {unknown}")

        confidence = obj.get("confidence")
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise LLMValidationError("confidence must be a number")
            confidence = float(confidence)
            if not 0.0 <= confidence <= 1.0:
                raise LLMValidationError("confidence must be between 0 and 1")

        def optional_text(key: str) -> str | None:
            value = obj.get(key)
            if value is None:
                return None
            if not isinstance(value, str):
                raise LLMValidationError(f"{key} must be a string or null")
            return value or None

        authority = optional_text("competent_authority")
        collaborators = obj.get("collaborating_units", [])
        missing_facts = obj.get("missing_facts", [])
        evidence_items = obj.get("evidence", [])
        decision_status = obj.get("decision_status", "needs_fact_check")
        if not isinstance(collaborators, list) or not all(isinstance(x, str) for x in collaborators):
            raise LLMValidationError("collaborating_units must be a list of strings")
        if not isinstance(missing_facts, list) or not all(isinstance(x, str) for x in missing_facts):
            raise LLMValidationError("missing_facts must be a list of strings")
        if decision_status not in {"supported", "needs_fact_check", "multi_agency"}:
            raise LLMValidationError("invalid decision_status")
        if not isinstance(evidence_items, list):
            raise LLMValidationError("evidence must be a list")
        checked_evidence: list[dict[str, str]] = []
        for item in evidence_items:
            if not isinstance(item, dict):
                continue
            evidence_id = item.get("evidence_id")
            claim = item.get("claim")
            quote = item.get("quote")
            if not all(isinstance(value, str) and value.strip() for value in (evidence_id, claim, quote)):
                continue
            source = evidence_by_id.get(evidence_id)
            if source is None or len(quote.strip()) < 8 or quote not in source.content:
                continue
            # Historical cases support routing experience, not a direct statutory duty.
            # Keep them as citations but never render them under “直接职责依据”.
            if source.knowledge_base_id != "historical_cases":
                heading = re.search(r"(?m)^##\s+(.+?)\s*$", source.content)
                source_label = heading.group(1).strip() if heading else (source.document_title or "职责来源")
                if source_label.startswith("区"):
                    source_label = f"白云{source_label}"
                checked_evidence.append({
                    "evidence_id": evidence_id,
                    "source": source_label,
                    "claim": claim,
                    "quote": quote,
                })

        if not department.strip():
            raise LLMValidationError("recommended_department must not be empty")
        if not conclusion.strip():
            raise LLMValidationError("conclusion must not be empty")

        return AnalysisResult(
            recommended_department=department,
            competent_authority=authority,
            collaborating_units=list(dict.fromkeys(x.strip() for x in collaborators if x.strip())),
            decision_status=decision_status,
            missing_facts=list(dict.fromkeys(x.strip() for x in missing_facts if x.strip())),
            evidence_items=checked_evidence,
            conclusion=conclusion,
            citation_references=list(dict.fromkeys(refs)),
            responsibility_boundary=optional_text("responsibility_boundary"),
            confidence=confidence,
            risk_warning=optional_text("risk_warning"),
        )

    def analyze(self, work_order: dict[str, Any], evidence: list[RetrievalResult],
                prompt_version: str) -> AnalysisResult:
        if not self.api_key:
            raise LLMConfigurationError("LLM_API_KEY is not configured")
        if not self.model:
            raise LLMConfigurationError("LLM_MODEL is not configured")

        evidence_pack = self._build_evidence_pack(evidence)
        user_prompt = (
            f"工单标题：{work_order.get('title') or ''}\n"
            f"工单正文：{work_order.get('content') or ''}\n"
            f"系统默认业务辖区：{work_order.get('system_default_jurisdiction') or '广州市白云区'}\n"
            f"本次研判案件辖区：{work_order.get('case_jurisdiction') or '广州市白云区'}\n"
            f"正文显式区名：{work_order.get('explicit_district') or '未在正文中写明'}\n"
            f"是否超出默认辖区：{'是' if work_order.get('outside_default_jurisdiction') else '否'}\n"
            f"研判参数：prompt_version={prompt_version}\n\n"
            f"【Evidence Pack】\n{evidence_pack}\n\n"
            "请按系统要求输出 JSON 研判结果。"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        text = self._chat(messages)
        obj = _extract_json_object(text)
        evidence_by_id = {item.evidence_id: item for item in evidence}
        result = self._validate(obj, evidence_by_id)
        return self._apply_consistency_rules(result, str(work_order.get("content") or ""), evidence_by_id)

    def analyze_stream(self, work_order: dict[str, Any], evidence: list[RetrievalResult], prompt_version: str):
        if not self.api_key:
            raise LLMConfigurationError("LLM_API_KEY is not configured")
        if not self.model:
            raise LLMConfigurationError("LLM_MODEL is not configured")
        evidence_pack = self._build_evidence_pack(evidence)
        user_prompt = (
            f"工单标题：{work_order.get('title') or ''}\n"
            f"工单正文：{work_order.get('content') or ''}\n"
            f"系统默认业务辖区：{work_order.get('system_default_jurisdiction') or '广州市白云区'}\n"
            f"本次研判案件辖区：{work_order.get('case_jurisdiction') or '广州市白云区'}\n"
            f"正文显式区名：{work_order.get('explicit_district') or '未在正文中写明'}\n"
            f"是否超出默认辖区：{'是' if work_order.get('outside_default_jurisdiction') else '否'}\n"
            f"研判参数：prompt_version={prompt_version}\n\n"
            f"【Evidence Pack】\n{evidence_pack}\n\n请按系统要求输出 JSON 研判结果。"
        )
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}]
        raw = ""
        for chunk in self._chat_stream(messages):
            raw += chunk
            yield chunk
        obj = _extract_json_object(raw)
        evidence_by_id = {item.evidence_id: item for item in evidence}
        result = self._validate(obj, evidence_by_id)
        return self._apply_consistency_rules(result, str(work_order.get("content") or ""), evidence_by_id)

    @staticmethod
    def _apply_consistency_rules(
        result: AnalysisResult,
        work_order_text: str,
        evidence_by_id: dict[str, RetrievalResult],
    ) -> AnalysisResult:
        """Restore the useful deterministic guardrails from the pre-V2 pipeline."""
        districts = [name for name in (
            "白云区", "天河区", "越秀区", "海珠区", "荔湾区", "黄埔区",
            "番禺区", "花都区", "南沙区", "从化区", "增城区",
        ) if name in work_order_text]
        facts = list(result.missing_facts)
        status = result.decision_status
        confidence = result.confidence
        department = result.recommended_department
        authority = result.competent_authority
        collaborators = result.collaborating_units
        conclusion = result.conclusion
        responsibility_boundary = result.responsibility_boundary
        risk_warning = result.risk_warning
        evidence_items = result.evidence_items
        citation_references = result.citation_references

        if len(districts) > 1:
            fact = f"工单同时出现{'、'.join(districts)}，须先核实准确属地"
            facts = [fact, *[item for item in facts if item != fact]]
            status = "needs_fact_check"
            confidence = min(confidence if confidence is not None else 0.3, 0.3)
            department = "暂不确定（须先核实准确属地）"
            authority = None
            collaborators = []
            conclusion = (
                f"工单同时出现{'、'.join(districts)}，现有信息无法可靠确定事项实际所在地。"
                "历史案例只能作为受理经验，不能替代本案地址核实；建议先确认准确区、镇街和具体点位，"
                "再按实际所在地及事项类型确定首派和业务主管单位。"
            )
            responsibility_boundary = "在准确属地确认前，不宜指定具体区级部门或镇街承担本案职责。"
            risk_warning = "应优先核实事发位置，避免跨区误派和重复转派；如事项正在发生，可先记录现场证据并联系实际所在地热线。"

        compact_text = re.sub(r"\s+", "", work_order_text)
        if "人和镇周口" in compact_text or "空港经济区" in compact_text or "机场控制区" in compact_text:
            fact = "须核实是否位于空港经济区等特殊管理区域及其实际管辖边界"
            if fact not in facts:
                facts.append(fact)
            status = "needs_fact_check"
            confidence = min(confidence if confidence is not None else 0.6, 0.6)

        cited = [evidence_by_id[item] for item in result.citation_references if item in evidence_by_id]
        has_direct_basis = any(item.knowledge_base_id != "historical_cases" for item in cited)
        if result.citation_references and not has_direct_basis:
            fact = "当前首派主要依据历史同类受理记录，仍需核实现行职责及具体管辖"
            if fact not in facts:
                facts.append(fact)
            status = "needs_fact_check"
            confidence = min(confidence if confidence is not None else 0.6, 0.6)

        if facts and status == "supported":
            status = "needs_fact_check"
        if status == "needs_fact_check":
            confidence = min(confidence if confidence is not None else 0.7, 0.7)
        if collaborators and status == "supported":
            status = "multi_agency"

        if re.search(r"路灯|道路照明|照明设施", work_order_text) and re.search(r"权属|移交|路灯编号", " ".join(facts) + work_order_text):
            status = "needs_fact_check"
            confidence = min(confidence if confidence is not None else 0.7, 0.7)

        def comparable_unit(value: str | None) -> str:
            normalized = re.sub(r"[（(].*?[）)]", "", value or "")
            normalized = normalized.replace("广州市", "").replace("人民政府-", "")
            return re.sub(r"\s+", "", normalized)

        primary_units = {comparable_unit(department), comparable_unit(authority)} - {""}
        collaborators = [
            unit for unit in collaborators if comparable_unit(unit) not in primary_units
        ]

        unsupported_risk_terms = []
        if not re.search(r"诈骗|骗取|冒充|欺诈", work_order_text):
            unsupported_risk_terms.extend(("诈骗", "报案", "公安机关"))
        if not re.search(r"聚集|群体|多人讨薪|冲突|威胁|情绪激动", work_order_text):
            unsupported_risk_terms.extend(("群体性", "情绪激动", "维稳"))
        if risk_warning and unsupported_risk_terms:
            sentences = re.split(r"(?<=[。！？；])", risk_warning)
            risk_warning = "".join(
                sentence for sentence in sentences
                if not any(term in sentence for term in unsupported_risk_terms)
            ).strip() or None

        if not re.search(r"公共秩序|聚集|群体|冲突", work_order_text):
            evidence_items = [
                item for item in evidence_items
                if "严重影响公共秩序事件" not in item.get("quote", "")
            ]
        if not re.search(r"托幼|幼儿园|卫生室", work_order_text):
            evidence_items = [
                item for item in evidence_items
                if "托幼机构" not in item.get("quote", "")
            ]
        if "职业健康检查" not in work_order_text:
            evidence_items = [
                item for item in evidence_items
                if "职业健康检查" not in item.get("quote", "")
            ]

        explicit_town = (
            re.search(r"白云区(?P<place>[\u4e00-\u9fff]{1,6}(?:街|镇))", work_order_text)
            or re.search(r"(?:^|[，,。；;\s])(?P<place>[\u4e00-\u9fff]{1,6}(?:街|镇))", work_order_text)
        )
        if explicit_town:
            facts = [
                fact for fact in facts
                if not re.search(r"确定|确认|明确", fact) or not re.search(r"属地|镇街", fact)
            ]
            if re.search(r"属地(?:街道办事处|镇人民政府|街道|镇街)", department):
                place = explicit_town.group("place")
                department = f"{place}道办事处" if place.endswith("街") else f"{place}人民政府"

        if not evidence_items and re.search(r"教育|学位|入学|招生|公办小学", work_order_text):
            for evidence_id, source in evidence_by_id.items():
                if source.knowledge_base_id != "department_duties":
                    continue
                heading = re.search(r"(?m)^##\s+(.+?)\s*$", source.content)
                if not heading:
                    continue
                source_label = heading.group(1).strip()
                if source_label.startswith("区"):
                    source_label = f"白云{source_label}"
                if comparable_unit(source_label) != comparable_unit(department):
                    continue
                lines = [line.strip() for line in source.content.splitlines() if line.strip()]
                candidates = [
                    line for line in lines
                    if len(line) >= 12 and re.search(r"义务教育|基础教育|招生计划|教育招生", line)
                ]
                if candidates:
                    quote = max(candidates, key=lambda line: sum(term in line for term in ("义务教育", "基础教育", "招生", "教育")))
                    evidence_items = [{
                        "evidence_id": evidence_id,
                        "source": source_label,
                        "claim": "该部门原文职责直接支持教育事项承办判断",
                        "quote": quote,
                    }]
                    citation_references = list(dict.fromkeys([*citation_references, evidence_id]))
                    break

        return replace(
            result,
            recommended_department=department,
            competent_authority=authority,
            collaborating_units=collaborators,
            decision_status=status,
            missing_facts=list(dict.fromkeys(facts)),
            confidence=confidence,
            conclusion=conclusion,
            responsibility_boundary=responsibility_boundary,
            risk_warning=risk_warning,
            evidence_items=evidence_items,
            citation_references=citation_references,
        )
