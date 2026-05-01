import os

from dotenv import load_dotenv


class TushareTokenError(RuntimeError):
    """Raised when Tushare token is missing."""


def create_tushare_client():
    load_dotenv()
    token = os.getenv("TUSHARE_API_TOKEN")
    if not token:
        raise TushareTokenError("TUSHARE_API_TOKEN is not configured")

    import tushare as ts

    ts.set_token(token)
    return ts.pro_api()
