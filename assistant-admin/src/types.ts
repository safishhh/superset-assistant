export type Provider = {
  id: number;
  name: string;
  base_url: string;
  has_api_key: boolean;
  api_key_hint: string;
  enabled: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type Model = {
  id: number;
  provider_id: number;
  provider_name: string;
  model_name: string;
  display_name: string;
  supports_tools: boolean;
  disable_thinking: boolean;
  context_window: number;
  input_price_per_m: number;
  output_price_per_m: number;
  is_default: boolean;
  enabled: boolean;
};

export type Conversation = {
  id: string;
  username: string;
  title: string;
  model_name: string;
  started_at: string;
  last_at: string;
  status: string;
  run_count: number;
  input_tokens: number;
  output_tokens: number;
  cost: number;
  deleted?: boolean;
  deleted_at?: string | null;
  employee_id?: number | null;
  employee_name?: string;
};

export type ConversationDetail = Conversation & {
  messages: Array<{
    id: number;
    run_id: string;
    role: string;
    content: string;
    model_name: string;
    input_tokens: number;
    output_tokens: number;
    latency_ms: number;
    status: string;
    error: string;
    selection?: Array<{
      kind?: string;
      chart_id?: string;
      title?: string;
      text?: string;
    }> | null;
    parts?: Array<
      { type: "text"; len: number } | { type: "tool"; name: string }
    > | null;
    created_at: string;
  }>;
  tool_calls: Array<{
    id: number;
    run_id: string;
    sequence: number;
    tool_name: string;
    args_json: unknown;
    result_json: unknown;
    sql_text: string;
    row_count: number;
    duration_ms: number;
    status: string;
    error: string;
    created_at: string;
  }>;
};

export type WriteAction = {
  id: string;
  username: string;
  conversation_id: string;
  run_id: string;
  action_type: string;
  risk_level: string;
  status: string;
  summary: string;
  plan: unknown;
  snapshot: unknown;
  result: unknown;
  rollback: unknown;
  error: string;
  created_at: string;
  expires_at: string;
  executed_at: string | null;
  rolled_back_at: string | null;
};

export type AdminOperation = {
  id: number;
  actor: string;
  action: string;
  target_type: string;
  target_id: string;
  before_json: unknown;
  after_json: unknown;
  ip: string;
  user_agent: string;
  created_at: string;
};

export type Overview = {
  days: number;
  totals: {
    requests: number;
    input_tokens: number;
    output_tokens: number;
    tokens: number;
    cost: number;
    tool_calls: number;
    errors: number;
  };
  quality: {
    tool_calls: number;
    tool_ok: number;
    tool_success_rate: number | null;
    feedback_up: number;
    feedback_down: number;
    feedback_total: number;
    feedback_adoption_rate: number | null;
  };
  daily: Array<{
    day: string;
    requests: number;
    tokens: number;
    cost: number;
    errors: number;
  }>;
  top_users: Array<{
    username: string;
    requests: number;
    tokens: number;
    cost: number;
  }>;
  top_models: Array<{
    model_name: string;
    requests: number;
    tokens: number;
  }>;
  top_tools: Array<{ tool_name: string; calls: number }>;
  recent_conversations: Conversation[];
};

export type AdminFilters = {
  users: string[];
  models: string[];
  model_providers?: Record<string, string>;
  employees: { id: number; name: string }[];
};

export type Usage = {
  days: number;
  group_by: string;
  username: string | null;
  model_name: string | null;
  start: string;
  end: string | null;
  items: Array<{
    key: string;
    day?: string;
    username?: string;
    model_name?: string;
    provider_name?: string | null;
    employee_id?: number;
    employee_name?: string;
    requests: number;
    input_tokens: number;
    output_tokens: number;
    tokens: number;
    cost: number;
    tool_calls: number;
    errors: number;
  }>;
  top_users: Array<{
    username: string;
    requests: number;
    tokens: number;
    cost: number;
  }>;
  top_models: Array<{
    model_name: string;
    provider_name?: string | null;
    requests: number;
    tokens: number;
    cost: number;
  }>;
  top_employees: Array<{
    employee_id: number;
    employee_name: string;
    requests: number;
    tokens: number;
    cost: number;
  }>;
};

export type Paged<T> = {
  total: number;
  page: number;
  page_size: number;
  items: T[];
};

export type DirectoryUser = {
  username: string;
  first_name: string;
  last_name: string;
  email: string;
  active: boolean;
  roles: string[];
  groups: string[];
  knowledge_active: number;
  knowledge_trash: number;
  ai_enabled: boolean;
};

export type DirectoryRole = {
  name: string;
  user_count: number;
  group_count: number;
};

export type RoleEmployee = {
  id: number;
  username: string;
  nickname: string;
  title: string;
  avatar: string;
  enabled: boolean;
  available: boolean;
};

export type RoleUser = {
  username: string;
  first_name: string;
  last_name: string;
  email: string;
  active: boolean;
  roles: string[];
  groups: string[];
};

export type AdminKnowledge = {
  id: number;
  username: string;
  title: string;
  content: string;
  source: string;
  created_at: string;
  updated_at: string;
};

export type LimitsConfig = {
  rate_per_minute: number;
  daily_requests: number;
  daily_tokens: number;
  daily_cost: number;
  updated_at: string | null;
  updated_by: string;
};

export type AgentLimitsConfig = {
  max_tool_calls: number;
  max_rows?: number;
  superset_sql_max_row?: number;
  updated_at: string | null;
  updated_by: string;
};

export type KnowledgeSettings = {
  user_max_entries: number;
  auto_max_entries: number;
  auto_ttl_days: number;
  trash_retention_days: number;
  auto_merge_enabled: boolean;
  updated_at: string | null;
  updated_by: string;
};

export type FeedbackDetail = {
  id: number;
  conversation_id: string;
  username: string;
  turn_index: number;
  rating: "up" | "down";
  comment: string;
  conversation_title: string;
  conversation_started_at: string | null;
  conversation_last_at: string | null;
  answer_preview: string;
  answer: string;
  created_at: string;
  updated_at: string;
};

export type AdminEmployee = {
  id: number;
  username: string;
  nickname: string;
  title: string;
  avatar: string;
  intro: string;
  greeting: string;
  persona: string;
  model_id: number | null;
  model_ids: number[] | null;
  can_delegate: boolean;
  delegate_employee_ids: number[] | null;
  skill_ids: number[];
  tools: string[] | null;
  /** null = 全员可见；[] = 仅管理员；列表 = 指定用户白名单 */
  users: string[] | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  updated_by: string;
};

export type SupersetUser = {
  username: string;
  display_name: string;
  active: boolean;
};

export type McpTool = {
  name: string;
  title: string;
  description: string;
  category: string;
  read_only: boolean;
  destructive: boolean;
  source: "mcp" | "agent";
  aliases: string[];
};

export type LogFile = {
  name: string;
  date: string;
  active: boolean;
  kind?: "agent" | "ai";
  size: number;
  modified: string;
};

export type LogSettings = {
  retention_days: number;
  updated_at: string | null;
  updated_by: string;
};

export type LogsResponse = {
  files: LogFile[];
  settings: LogSettings;
  log_dir: string;
  default_retention_days: number;
};

export type LogTail = {
  name: string;
  lines: string[];
  level?: string;
  size: number;
  modified: string;
};

export type AiCallEntry = {
  ts?: string;
  kind?: string;
  purpose?: string;
  model?: string;
  stream?: boolean;
  user?: string;
  employee?: string;
  conversation_id?: string;
  run_id?: string;
  messages?: number;
  tools?: number;
  latency_ms?: number;
  ttft_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  cache_read_tokens?: number;
  tool_calls?: string[];
  finish_reason?: string | null;
  state?: string;
  status?: string;
  error?: string;
};

export type AiCallsResponse = {
  items: AiCallEntry[];
  scanned: number;
  truncated: boolean;
};
