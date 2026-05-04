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

    # Pass token into pro_api so tushare does not call set_token() (writes ~/tk.csv),
    # which can raise PermissionError under hardened / sandboxed home dirs.
    return ts.pro_api(token)
