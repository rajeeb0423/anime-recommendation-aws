import streamlit as st
import pandas as pd
import re
import boto3
import io
import json

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="🎌 Anime Explorer",
    page_icon="🎌",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .anime-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #0f3460;
        border-radius: 12px;
        padding: 12px;
        text-align: center;
        height: 100%;
        transition: transform 0.2s;
    }
    .anime-card:hover { transform: scale(1.02); border-color: #e94560; }
    .anime-title {
        color: #e94560;
        font-weight: 700;
        font-size: 13px;
        margin: 8px 0 4px 0;
        line-height: 1.3;
        min-height: 34px;
    }
    .anime-score {
        color: #ffd700;
        font-size: 18px;
        font-weight: 800;
    }
    .anime-meta {
        color: #a8b2d8;
        font-size: 11px;
        margin-top: 4px;
    }
    .rank-badge {
        background: #e94560;
        color: white;
        border-radius: 50%;
        width: 26px;
        height: 26px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-weight: 800;
        font-size: 12px;
    }
    .section-header {
        color: #e94560;
        border-bottom: 2px solid #e94560;
        padding-bottom: 6px;
        margin-bottom: 16px;
    }
    .stApp { background-color: #0d1117; }
    .search-result-card {
        background: #1a1a2e;
        border-left: 4px solid #e94560;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 12px;
    }
    img { border-radius: 8px; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=600)
def load_data_from_s3() -> pd.DataFrame:
    s3 = boto3.client(
        "s3",
        aws_access_key_id     = st.secrets["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key = st.secrets["AWS_SECRET_ACCESS_KEY"],
        region_name           = st.secrets["AWS_DEFAULT_REGION"],
    )
    bucket = st.secrets["s3"]["bucket_name"]
    key    = st.secrets["s3"]["file_key"]
    obj    = s3.get_object(Bucket=bucket, Key=key)
    return pd.read_csv(io.BytesIO(obj["Body"].read()))

# ── Data loading ──────────────────────────────────────────────────────────────
@st.cache_data
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["score"] = pd.to_numeric(df["score"], errors="coerce")
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
    df["popularity"] = pd.to_numeric(df["popularity"], errors="coerce")
    df["episodes"] = pd.to_numeric(df["episodes"], errors="coerce")
    df["members"] = pd.to_numeric(df["members"], errors="coerce")
    df["genre"] = df["genre"].fillna("Unknown")
    df["synopsis"] = df["synopsis"].fillna("No synopsis available.")
    df["studios"] = df["studios"].fillna("Unknown")
    df["type"] = df["type"].fillna("Unknown")
    return df


@st.cache_data
def get_all_genres(df: pd.DataFrame):
    """Extract unique genres from comma-separated genre column."""
    genres = set()
    for g in df["genre"].dropna():
        for item in str(g).split(","):
            clean = item.strip()
            if clean and clean.lower() != "unknown":
                genres.add(clean)
    return sorted(genres)


# ── Natural language keyword search ──────────────────────────────────────────
def nl_search(df: pd.DataFrame, query: str, top_n: int = 10) -> pd.DataFrame:
    """
    Score each row by how many query tokens appear in
    title + synopsis + genre + studios (case-insensitive).
    Returns top_n results ranked by match count, then score.
    """
    tokens = re.findall(r"[a-zA-Z0-9]+", query.lower())
    if not tokens:
        return pd.DataFrame()

    search_text = (
        df["title"].fillna("").str.lower()
        + " "
        + df["synopsis"].fillna("").str.lower()
        + " "
        + df["genre"].fillna("").str.lower()
        + " "
        + df["studios"].fillna("").str.lower()
        + " "
        + df["type"].fillna("").str.lower()
    )

    match_counts = search_text.apply(
        lambda txt: sum(1 for t in tokens if t in txt)
    )
    df = df.copy()
    df["_matches"] = match_counts
    result = df[df["_matches"] > 0].sort_values(
        ["_matches", "score"], ascending=[False, False]
    ).head(top_n)
    return result.drop(columns=["_matches"])


# ── Anime card renderer ───────────────────────────────────────────────────────
def render_anime_card(col, row, rank: int):
    with col:
        img_url = row.get("image_url", "")
        score = row.get("score", "N/A")
        title = row.get("title", "Unknown")
        anime_type = row.get("type", "")
        episodes = row.get("episodes", "")
        genre = str(row.get("genre", ""))[:50]

        ep_txt = f"{int(episodes)} ep" if pd.notna(episodes) and str(episodes).replace(".0","").isdigit() else ""

        card_html = f"""
        <div class="anime-card">
            <span class="rank-badge">#{rank}</span>
        </div>"""
        # render image then metadata
        st.markdown(f'<div style="text-align:center"><span class="rank-badge">#{rank}</span></div>', unsafe_allow_html=True)
        if img_url and str(img_url).startswith("http"):
            st.image(img_url, use_container_width=True)
        else:
            st.markdown("🎌", unsafe_allow_html=True)

        st.markdown(
            f'<p class="anime-title">{title}</p>'
            f'<p class="anime-score">⭐ {score}</p>'
            f'<p class="anime-meta"><span style="color:#e94560;font-weight:bold">{anime_type}</span></p>',
            unsafe_allow_html=True,
        )


# ── Main app ──────────────────────────────────────────────────────────────────
def main():
    st.markdown("# 🎌 Anime Explorer")
    st.markdown("Discover and explore the top-rated anime of all time.")

    # ── Sidebar – File upload + filters ──────────────────────────────────────
    with st.sidebar:
        st.markdown("## 📂 Load Data")
        
        try:
            df_raw = load_data_from_s3()
            st.success("✅ Data loaded from S3")
        except Exception as e:
            st.error(f"Failed to load data from S3: {e}")
            st.stop()

        all_genres = get_all_genres(df_raw)

        st.markdown("---")
        st.markdown("## 🎛️ Filters")

        # Genre multiselect
        selected_genres = st.multiselect(
            "🎭 Genre",
            options=all_genres,
            default=[],
            placeholder="All genres",
        )

        # Anime type
        all_types = sorted(df_raw["type"].dropna().unique().tolist())
        selected_types = st.multiselect(
            "📺 Type",
            options=all_types,
            default=[],
            placeholder="All types",
        )

        # Score slider
        min_score = float(df_raw["score"].dropna().min())
        max_score = float(df_raw["score"].dropna().max())
        score_range = st.slider(
            "⭐ Score range",
            min_value=round(min_score, 1),
            max_value=round(max_score, 1),
            value=(round(min_score, 1), round(max_score, 1)),
            step=0.1,
        )

    # ── Apply sidebar filters ─────────────────────────────────────────────────
    df_filtered = df_raw.copy()

    if selected_genres:
        mask = df_filtered["genre"].apply(
            lambda g: any(sg in str(g) for sg in selected_genres)
        )
        df_filtered = df_filtered[mask]

    if selected_types:
        df_filtered = df_filtered[df_filtered["type"].isin(selected_types)]

    df_filtered = df_filtered[
        (df_filtered["score"] >= score_range[0])
        & (df_filtered["score"] <= score_range[1])
    ]

    # ── Top 10 section ────────────────────────────────────────────────────────
    st.markdown('<h2 class="section-header">🏆 Top 10 Anime</h2>', unsafe_allow_html=True)

    label_parts = []
    if selected_genres:
        label_parts.append(", ".join(selected_genres))
    if selected_types:
        label_parts.append(", ".join(selected_types))
    if label_parts:
        st.caption(f"Filtered by: {' · '.join(label_parts)} · Score {score_range[0]}–{score_range[1]}")

    top10 = df_filtered.dropna(subset=["score"]).sort_values("score", ascending=False).head(10)

    if top10.empty:
        st.warning("No anime found with the current filters. Try adjusting your criteria.")
    else:
        # Display in rows of 5
        rows_data = [top10.iloc[:5], top10.iloc[5:10]]
        for i, row_group in enumerate(rows_data):
            if row_group.empty:
                break
            cols = st.columns(5)
            for j, (_, row) in enumerate(row_group.iterrows()):
                render_anime_card(cols[j], row, rank=i * 5 + j + 1)
            st.markdown("<br>", unsafe_allow_html=True)

    # ── Filtered table ────────────────────────────────────────────────────────
    with st.expander("📋 View Full Filtered Results Table", expanded=False):
        display_df = df_filtered.dropna(subset=["score"]).sort_values("score", ascending=False).reset_index(drop=True)
        # Don't display index in the table view.
        st.dataframe(
            display_df[["rank","image_url", "title", "score", "type", "episodes", "genre", "studios"]],
            column_config={
                "image_url": st.column_config.ImageColumn("Poster", width="small"),
                "title": st.column_config.TextColumn("Title", width="large"),
                "score": st.column_config.NumberColumn("Score", format="%.2f"),
                "members": st.column_config.NumberColumn("Members", format="%d"),
                },
            use_container_width=True,
            height=400,
            hide_index=True,
        )
        st.caption(f"Showing {len(display_df):,} anime")

    # ── Natural language search ───────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<h2 class="section-header">🔍 Natural Language Search</h2>', unsafe_allow_html=True)
    st.markdown("Describe an anime in plain English and we'll find the closest matches using semantic similarity.")

    query = st.text_input(
        "Search anime",
        placeholder="e.g. 'An anime about a samurai who fights demons'",
        label_visibility="collapsed",
    )
    search_btn = st.button("Search 🔍", use_container_width=False)

    if search_btn and query:
        with st.spinner("Searching..."):
            try:
                # Invoke the search Lambda with only the query description
                lambda_client = boto3.client(
                    "lambda",
                    aws_access_key_id     = st.secrets["AWS_ACCESS_KEY_ID"],
                    aws_secret_access_key = st.secrets["AWS_SECRET_ACCESS_KEY"],
                    region_name           = st.secrets["AWS_DEFAULT_REGION"],
                )
                response = lambda_client.invoke(
                    FunctionName   = st.secrets["SEARCH_LAMBDA_NAME"],
                    InvocationType = "RequestResponse",
                    Payload        = json.dumps({"query": query}),
                )
                body    = json.loads(json.loads(response["Payload"].read())["body"])
                results = body.get("results", [])

                if not results:
                    st.warning("No results found. Try a different description.")
                else:
                    # Build lookup: anime_id → similarity_score
                    score_map = {r["anime_id"]: r["similarity_score"] for r in results}
                    order_map = {r["anime_id"]: i for i, r in enumerate(results)}

                    # Join against the already-loaded df_raw
                    matched = df_raw[df_raw["anime_id"].isin(score_map.keys())].copy()
                    matched["similarity_score"] = matched["anime_id"].map(score_map)
                    matched["_order"]           = matched["anime_id"].map(order_map)
                    matched = matched.sort_values(["similarity_score", "score"],ascending=[False, False]).drop(columns=["_order"]).reset_index(drop=True)

                    st.success(f"Found **{len(matched)}** results for: *{query}*")

                    for _, row in matched.iterrows():
                        img_url    = str(row.get("image_url", ""))
                        title      = row.get("title", "Unknown")
                        score      = row.get("score", "N/A")
                        genre      = str(row.get("genre", ""))
                        synopsis   = str(row.get("synopsis", ""))[:300]
                        anime_type = str(row.get("type", ""))
                        studios    = str(row.get("studios", ""))
                        sim        = row.get("similarity_score", 0)
                        episodes   = row.get("episodes", "")
                        ep_txt     = f"• {int(episodes)} ep" if pd.notna(episodes) and str(episodes).replace(".0","").isdigit() else ""

                        res_col1, res_col2 = st.columns([1, 4])
                        with res_col1:
                            if img_url.startswith("http"):
                                st.image(img_url, width=120)
                        with res_col2:
                            st.markdown(
                                f'<div class="search-result-card">' +
                                f'<strong style="color:#e94560;font-size:15px">{title}</strong><br>' +
                                f'<span style="color:#ffd700">⭐ {score}</span> &nbsp;' +
                                f'<span style="color:#a8b2d8">{anime_type} {ep_txt} &nbsp;|&nbsp; 🎬 {studios}</span><br>' +
                                f'<span style="color:#7b8ec8;font-size:12px">🎭 {genre}</span> &nbsp;' +
                                f'<span style="color:#4caf50;font-size:12px">🎯 Similarity: {sim}</span><br><br>' +
                                f'<span style="color:#ccd6f6;font-size:13px">{synopsis}{"..." if len(str(row.get("synopsis",""))) > 300 else ""}</span>' +
                                f'</div>',
                                unsafe_allow_html=True,
                            )
                        st.markdown("")

            except Exception as e:
                st.error(f"Search failed: {e}")

    elif search_btn and not query:
        st.warning("Please enter a description to search.")


if __name__ == "__main__":
    main()
