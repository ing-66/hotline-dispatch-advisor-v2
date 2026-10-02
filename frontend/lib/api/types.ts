export interface PaginatedResponse<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export interface WorkOrder {
  id: string;
  source_case_id: string | null;
  title: string;
  content: string;
  request_type: string | null;
  address: string | null;
  source: string | null;
  event_time: string | null;
  actual_department_id: string | null;
  status: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Analysis {
  id: string;
  work_order_id: string;
  conversation_id: string | null;
  model_provider: string;
  model_name: string;
  prompt_version: string;
  recommended_department_text: string | null;
  recommended_departments_json?: Array<{
    role?: string;
    unit?: string;
    value?: string;
  }>;
  conclusion: string;
  responsibility_boundary: string | null;
  confidence: number | null;
  risk_warning: string | null;
  evidence_summary: string | null;
  raw_output_json?: {
    citation_references?: string[];
    decision_status?: string;
    missing_facts?: string[];
    evidence?: Array<{ evidence_id: string; source?: string; claim: string; quote: string }>;
  };
  created_at: string;
}

export interface CitationMetadata {
  work_order_id?: string;
  source_case_id?: string;
  source_type?: string;
  document_header?: boolean;
  [key: string]: unknown;
}

export interface Citation {
  id: string;
  analysis_id: string;
  knowledge_base_id: string | null;
  evidence_id: string;
  document_id: string | null;
  document_title: string | null;
  external_id: string | null;
  point_id: string | null;
  content_snapshot: string;
  citation_type: string;
  score: number | null;
  metadata: CitationMetadata;
  created_at: string;
}

export interface Feedback {
  id: string;
  analysis_id: string;
  user_id: string | null;
  feedback_type: string;
  adopted: boolean | null;
  final_department_id: string | null;
  comment: string | null;
  created_at: string;
}

export interface SavedCase {
  id: string;
  work_order_id: string;
  analysis_id: string | null;
  user_id: string | null;
  case_type: string;
  note: string | null;
  created_at: string;
}

export interface Conversation {
  id: string;
  user_id: string | null;
  title: string;
  status: string;
  created_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: string;
  content: string;
  model_name: string | null;
  analysis_id: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface AnalysisResultBundle {
  workOrder: WorkOrder;
  analysis: Analysis;
  citations: Citation[];
}
