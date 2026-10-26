import yfinance as yf


class YFinanceSource:
    def get_quote(self, ticker: str) -> dict:
        info = yf.Ticker(ticker).fast_info
        price = info["last_price"]
        prev = info["previous_close"]
        return {
            "ticker": ticker,
            "price": price,
            "previous_close": prev,
            "change_pct": (price - prev) / prev * 100 if prev else None,
            "currency": info["currency"],
        }
