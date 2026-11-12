import os

from superset.config import CeleryConfig as _DefaultCeleryConfig

try:
    import MySQLdb  # noqa: F401
except ImportError:
    import pymysql

    pymysql.install_as_MySQLdb()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

SQLALCHEMY_DATABASE_URI = os.environ["SUPERSET_METADATA_URI"]
SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

APP_NAME = "Superset Assistant"
SUPERSET_LOAD_EXAMPLES = False

# 导航栏语言切换（/lang/<locale> 会写 session locale 并跳回原页面）
LANGUAGES = {
    "en": {"flag": "us", "name": "English"},
    "zh": {"flag": "cn", "name": "中文"},
}

FEATURE_FLAGS = {
    "ENABLE_EXTENSIONS": True,
    "FAB_API_KEY_ENABLED": True,
    "RLS_IN_SQLLAB": True,
    "ALERT_REPORTS": True,
    # 以下四项上游默认开，但本项目不用，显式关掉（menu_cond 会同时隐藏对应菜单）：
    # GTF 只服务异步图表取数，而 GLOBAL_ASYNC_QUERIES 关着 → tasks 表永远空，
    # 关掉同时移除 /api/v1/task/* 路由与 MCP 的 list_tasks/get_task_info。
    "GLOBAL_TASK_FRAMEWORK": False,
    # 未配 SLACK_API_TOKEN、无 Slack 收件人。
    "ALERT_REPORT_SLACK_V2": False,
    # 没有在看板里用 CSS 模板（模板页曾有一条 1 字节的测试数据）。
    "CSS_TEMPLATES": False,
    # 不需要图表的「嵌入代码」入口。
    "EMBEDDABLE_CHARTS": False,
    # 2026-10-31 按需打开的能力（上游默认都是关）：
    # 报表/告警 SQL 与邮件正文支持 Jinja 模板；描述里的 HTML 一律转义；数据集文件夹；
    # 实验性图表插件；相对时间范围 + 时间平移；Table v2 时间对比；缩略图；
    # 报表失败重试；邮件主题带日期；看板移动端布局。
    "ENABLE_TEMPLATE_PROCESSING": True,
    "ESCAPE_MARKDOWN_HTML": True,
    "DATASET_FOLDERS": True,
    "CHART_PLUGINS_EXPERIMENTAL": True,
    "DATE_RANGE_TIMESHIFTS_ENABLED": True,
    "TABLE_V2_TIME_COMPARISON_ENABLED": True,
    "THUMBNAILS": True,
    "ALERT_REPORTS_RETRY": True,
    "DATE_FORMAT_IN_EMAIL_SUBJECT": True,
    "MOBILE_CONSUMPTION_MODE": True,
}

# 缩略图缓存：默认是 NullCache，/thumbnail 永远回 202、图片从不落盘。
# 复用 Redis（worker 已在跑，镜像里带 Playwright/Chromium）。
THUMBNAIL_CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 7 * 24 * 3600,
    "CACHE_KEY_PREFIX": "superset_thumbnails_",
    "CACHE_REDIS_URL": os.environ.get(
        "THUMBNAIL_REDIS_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}/2"
    ),
}

# FAB 的两个开关互相独立：FEATURE_FLAGS 里的同名项只管前端面板可见性，
# 顶层这项才决定 FAB 把 ApiKeyApi 路由注册不注册（superset/config.py:2117-2122）。
FAB_API_KEY_ENABLED = True
# MCP 传输默认（None）会回退跟随 FAB_API_KEY_ENABLED，这里显式按住：
# 助手链路仍只认 /token 签发的短期 JWT，不接受长期 API key。
MCP_API_KEY_ENABLED = False

EXTENSIONS_PATH = "/app/extensions"
LOCAL_EXTENSIONS = (
    ["/app/local_extensions/assistant"]
    if os.path.isdir("/app/local_extensions/assistant")
    else []
)

MCP_AUTH_ENABLED = True
MCP_RBAC_ENABLED = True
MCP_JWT_ALGORITHM = os.environ.get("MCP_JWT_ALGORITHM", "HS256")
MCP_JWT_SECRET = os.environ["MCP_JWT_SECRET"]
MCP_JWT_ISSUER = os.environ.get("MCP_JWT_ISSUER", "assistant")
MCP_JWT_AUDIENCE = os.environ.get("MCP_JWT_AUDIENCE", "superset-mcp")
MCP_TOKEN_TTL = int(os.environ.get("AGENT_TOKEN_TTL", "300"))

ADMIN_TICKET_SECRET = os.environ.get("ADMIN_TICKET_SECRET", "")
ADMIN_TICKET_AUDIENCE = os.environ.get(
    "ADMIN_TICKET_AUDIENCE", "assistant-admin"
)
ADMIN_TICKET_ISSUER = os.environ.get("ADMIN_TICKET_ISSUER", "assistant")
ASSISTANT_ADMIN_URL = os.environ.get("ASSISTANT_ADMIN_URL", "")
# 宿主发布端口：浏览器直连 Agent、扩展后台跳转都用它（容器内仍是 28088）
ASSISTANT_AGENT_PORT = int(os.environ.get("AGENT_HTTP_PORT", "28088"))

TALISMAN_ENABLED = False
SESSION_COOKIE_SECURE = False

SQLALCHEMY_ENGINE_OPTIONS = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}
if SQLALCHEMY_DATABASE_URI.startswith("sqlite:"):
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"timeout": 30, "check_same_thread": False},
    }

# Local demo MySQL data source. Re-enable this in production.
PREVENT_UNSAFE_DB_CONNECTIONS = False

# The assistant only needs read access for phase 1/2.
ROW_LIMIT = 5000
SQL_MAX_ROW = 5000
SUPERSET_WEBSERVER_TIMEOUT = 120

# ---------------------------------------------------------------- 邮件 / SMTP
# 占位值只用于打通配置；把 infra/.env 里的 SMTP_* 换成真实值并重建
# superset / superset-worker / superset-beat 后即可真实发信。
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.example.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "placeholder@example.com")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "placeholder")
SMTP_MAIL_FROM = os.environ.get("SMTP_MAIL_FROM", SMTP_USER)
SMTP_STARTTLS = _env_bool("SMTP_STARTTLS", True)
SMTP_SSL = _env_bool("SMTP_SSL", False)
SMTP_SSL_SERVER_AUTH = _env_bool("SMTP_SSL_SERVER_AUTH", True)
SMTP_TIMEOUT = int(os.environ.get("SMTP_TIMEOUT", "30"))
EMAIL_REPORTS_SUBJECT_PREFIX = os.environ.get(
    "EMAIL_REPORTS_SUBJECT_PREFIX", "[Superset] "
)

# 报表截图走容器内地址；邮件正文里的链接给浏览器可访问的地址。
WEBDRIVER_BASEURL = os.environ.get("WEBDRIVER_BASEURL", "http://superset:8088/")
WEBDRIVER_BASEURL_USER_FRIENDLY = os.environ.get(
    "WEBDRIVER_BASEURL_USER_FRIENDLY", "http://localhost:8088/"
)


# Alerts & Reports 由 celery worker + beat 执行。继承默认 CeleryConfig，
# 保留 retention 等 beat 任务，只把 broker/backend 指到 Redis。
class CeleryConfig(_DefaultCeleryConfig):
    broker_url = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
    result_backend = os.environ.get(
        "CELERY_RESULT_BACKEND", "redis://redis:6379/1"
    )


CELERY_CONFIG = CeleryConfig
