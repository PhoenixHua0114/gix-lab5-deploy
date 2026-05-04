import streamlit as st
import os
import re
import csv
import io
import requests
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="GIX Asset Intake Tool", layout="wide")

st.markdown("""
<style>
@media (max-width: 480px) {
    h1 { font-size: 1.5rem !important; }
}
</style>
""", unsafe_allow_html=True)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

CATEGORIES = ["IT Equipment", "Maker Space", "Audio/Visual", "Other"]

def clean_title(raw: str) -> str:
    raw = re.sub(r'[Ff]or\s+(iPhone|Android|iPad|Samsung|Galaxy|Mac|Windows|USB[-\s]?C|USB[-\s]?A)[\w\s,/.-]*', '', raw)
    raw = re.sub(r'\b(compatible with|works with|fits|supports)\b.*', '', raw, flags=re.IGNORECASE)
    raw = re.sub(r'\b\d+\s*(pack|pcs|pieces|count|ft|feet|inch|inches|mm|cm|meters?|gb|tb|mah)\b.*', '', raw, flags=re.IGNORECASE)
    raw = re.sub(r'\([^)]*\)', '', raw)
    raw = re.sub(r'\[[^\]]*\]', '', raw)
    raw = re.sub(r'[-|,]\s*$', '', raw.strip())
    words = raw.strip().split()
    return ' '.join(words[:6]).strip()

def lookup_upc(upc: str) -> dict:
    try:
        response = requests.get(
            f"https://api.upcitemdb.com/prod/trial/lookup?upc={upc}",
            timeout=5
        )
        assert response.status_code == 200, f"UPC API returned {response.status_code}"
        data = response.json()
        assert "items" in data, "Response missing 'items' key"
        assert isinstance(data["items"], list), "Expected items to be a list"
        if data["items"]:
            item = data["items"][0]
            return {"title": item.get("title", ""), "brand": item.get("brand", "")}
        return {}
    except requests.exceptions.Timeout:
        st.warning("UPC lookup timed out. Please enter the title manually.")
        return {}
    except AssertionError as e:
        st.warning(f"UPC API error: {e}")
        return {}
    except Exception as e:
        st.warning(f"Could not look up UPC: {e}")
        return {}

def generate_asset_tag() -> str:
    import random
    return str(random.randint(10000000, 99999999))

st.title("GIX Asset Intake Tool")
st.caption("Clean Amazon-style product titles and generate Blue Tally-ready CSV entries.")

st.header("Add New Asset")

st.subheader("Option 1: Look up by UPC barcode")
upc_input = st.text_input("Scan or enter UPC barcode", placeholder="e.g. 012345678905")
upc_title = ""
if upc_input.strip():
    result = lookup_upc(upc_input.strip())
    if result:
        upc_title = f"{result.get('brand', '')} {result.get('title', '')}".strip()
        st.success(f"Found: **{upc_title}**")
    else:
        st.info("No results found for this UPC. Use Option 2 below.")

st.subheader("Option 2: Paste Amazon-style title")

with st.form("intake_form"):
    raw_title = st.text_area(
        "Product title",
        value=upc_title,
        height=100,
        placeholder="e.g. Hollyland Lark M2 Wireless Microphone for iPhone 15 16 17 Android"
    )
    category = st.selectbox("Category", CATEGORIES)
    col1, col2 = st.columns(2)
    with col1:
        custom_tag = st.text_input("Asset tag (leave blank to auto-generate)", max_chars=8)
    with col2:
        status = st.selectbox("Status", ["Ready to deploy", "In use", "Consumed", "Missing"])
    submitted = st.form_submit_button("Clean & Save")

if submitted:
    if not raw_title.strip():
        st.error("Please enter a product title.")
    else:
        clean = clean_title(raw_title)
        tag = custom_tag.strip() if custom_tag.strip() else generate_asset_tag()
        try:
            response = supabase.table("assets").insert({
                "raw_title": raw_title.strip(),
                "clean_name": clean,
                "asset_tag": tag,
                "category": category,
                "status": status
            }).execute()
            assert response.data, "Insert returned no data"
            st.success(f"Saved! Clean name: **{clean}** | Tag: `{tag}`")
        except Exception as e:
            st.error(f"Database error: {e}")

st.divider()
st.header("Asset Inventory")

try:
    result = supabase.table("assets").select("*").order("created_at", desc=True).execute()
    assets = result.data
    assert isinstance(assets, list), "Expected a list from Supabase"

    if not assets:
        st.info("No assets yet. Add one above!")
    else:
        cat_filter = st.selectbox("Filter by category", ["All"] + CATEGORIES)
        filtered = assets if cat_filter == "All" else [a for a in assets if a["category"] == cat_filter]
        st.write(f"{len(filtered)} asset(s) found")

        for a in filtered:
            with st.expander(f"{a['clean_name']} — `{a['asset_tag']}`"):
                st.write(f"**Raw title:** {a['raw_title']}")
                st.write(f"**Category:** {a['category']} | **Status:** {a['status']}")
                st.write(f"**Created:** {a['created_at'][:10]}")

        st.divider()
        st.subheader("Export to Blue Tally CSV")
        if st.button("Download CSV"):
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=["asset_name", "asset_tag", "category", "status"])
            writer.writeheader()
            for a in filtered:
                writer.writerow({
                    "asset_name": a["clean_name"],
                    "asset_tag": a["asset_tag"],
                    "category": a["category"],
                    "status": a["status"]
                })
            st.download_button("Click to download", output.getvalue(), "blue_tally_import.csv", "text/csv")

except Exception as e:
    st.error(f"Could not load assets: {e}")