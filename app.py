import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data

st.set_page_config(page_title="Equities Dashboard", layout="wide")


@st.cache_data(ttl=900, show_spinner="Fetching Yahoo Finance data...")
def get_metrics(tickers: tuple[str, ...]) -> pd.DataFrame:
    return data.fetch_all(list(tickers))


@st.cache_data(ttl=900)
def get_history(ticker: str) -> pd.DataFrame:
    return data.fetch_history(ticker, "1y")


@st.cache_data(ttl=900)
def get_news(ticker: str) -> list[dict]:
    return data.fetch_news(ticker)


st.title("Equities Dashboard")
tickers = tuple(data.load_tickers())
df = get_metrics(tickers)

top = st.columns([6, 1])
top[0].caption("Source: Yahoo Finance (free, unofficial; ~15 min cache). Edit `tickers.txt` to add names.")
if top[1].button("Refresh"):
    st.cache_data.clear()
    st.rerun()

fmt = {
    "Price": "${:,.2f}", "Day %": "{:+.1f}%", "52W High": "${:,.2f}", "52W Low": "${:,.2f}",
    "% from High": "{:+.1f}%", "% from Low": "{:+.1f}%", "Mkt Cap ($B)": "{:,.1f}", "EV ($B)": "{:,.1f}",
    "LTM P/E": "{:.1f}x", "NTM P/E": "{:.1f}x", "LTM EV/EBITDA": "{:.1f}x", "NTM EV/EBITDA": "{:.1f}x",
    "NTM Rev Growth %": "{:+.1f}%", "EBITDA Margin %": "{:.1f}%", "Net Debt/EBITDA": "{:.1f}x",
    "Target": "${:,.2f}", "Upside %": "{:+.1f}%", "Rating (1=Buy, 5=Sell)": "{:.1f}", "# Analysts": "{:.0f}",
}
table_cols = [
    "Ticker", "Company", "Price", "Day %", "52W High", "52W Low", "% from High", "% from Low",
    "Mkt Cap ($B)", "EV ($B)", "LTM P/E", "NTM P/E", "LTM EV/EBITDA", "NTM EV/EBITDA",
    "NTM Rev Growth %", "EBITDA Margin %", "Net Debt/EBITDA", "Target", "Upside %",
    "Rating (1=Buy, 5=Sell)", "# Analysts", "Next Earnings",
]
view = df[[c for c in table_cols if c in df.columns]].set_index("Ticker")


def color_move(v):
    if pd.isna(v):
        return ""
    return "color: #1a9850" if v > 0 else "color: #d73027" if v < 0 else ""


styled = view.style.format(fmt, na_rep="N/A").map(
    color_move, subset=["Day %", "Upside %", "NTM Rev Growth %"]
)
st.dataframe(styled, use_container_width=True, height=36 * (len(view) + 1) + 3)

st.caption(
    "**Methodology.** LTM P/E = price / trailing EPS (actuals). NTM P/E = price / time-weighted blend of "
    "current-FY and next-FY consensus EPS. LTM EV/EBITDA uses trailing actual EBITDA. NTM EV/EBITDA is an "
    "**approximation**: Yahoo has no EBITDA consensus, so LTM EBITDA is scaled by consensus NTM revenue growth "
    "(constant margin). Negative earnings/EBITDA show N/A. Recent IPOs (MAIR, INIO, DPC) have thin history and "
    "few analysts; spin-off names (e.g. HON) can show distorted LTM vs NTM comparisons because actuals include "
    "divested businesses while consensus does not."
)

st.divider()
sel = st.selectbox("Detail view", list(tickers))
row = df[df["Ticker"] == sel].iloc[0]
c1, c2 = st.columns([3, 2])

with c1:
    h = get_history(sel)
    if not h.empty:
        fig = go.Figure(go.Scatter(x=h.index, y=h["Close"], mode="lines", name=sel))
        if pd.notna(row.get("52W High")):
            fig.add_hline(y=row["52W High"], line_dash="dot", annotation_text="52W high")
        if pd.notna(row.get("52W Low")):
            fig.add_hline(y=row["52W Low"], line_dash="dot", annotation_text="52W low")
        fig.update_layout(title=f"{sel} - 1Y price", height=380, margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig, use_container_width=True)

with c2:
    st.subheader("Headlines")
    try:
        for n in get_news(sel)[:10]:
            when = n["published"].strftime("%b %d %H:%M") if n["published"] else ""
            st.markdown(f"- [{n['title']}]({n['link']})  \n  <small>{when}</small>", unsafe_allow_html=True)
    except Exception as e:
        st.warning(f"News unavailable: {e}")
