from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    GEMINI_API_KEY: str = ""
    # Ordered fallback list; first model that has quota wins.
    GEMINI_MODELS: str = "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.8-flash"
    GMAIL_USER: str = ""
    GMAIL_APP_PASSWORD: str = ""
    REPORT_RECIPIENT: str = ""
    RECIPIENT_NAME: str = "there"  # greeting in the email body, e.g. "Hi Caroline,"
    COMPANY_NAME: str = "Your Company"  # printed on the PDF; not a real default, set it in .env
    EMPLOYEE_NAME: str = "Employee Name"  # printed on the PDF and in the email subject
    GOOGLE_CLIENT_ID: str = ""
    ALLOWED_EMAILS: str = ""  # comma-separated
    SESSION_SECRET: str = ""

    @property
    def models(self) -> list[str]:
        return [m.strip() for m in self.GEMINI_MODELS.split(",") if m.strip()]

    @property
    def allowed_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.ALLOWED_EMAILS.split(",") if e.strip()}


settings = Settings()
