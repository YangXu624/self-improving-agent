"""Product catalogue browser for Streamlit UI.

Provides an interactive, scrollable catalogue exploration page:
- Keyword search with BM25 ranking across 50,000 verified products
- Category and facet filtering (Clothing, Shoes, Jewelry, Bags, etc.)
- Price range constraints and price-verification toggles
- Sorting options (Relevance, Price Low/High, Rating)
- Responsive multi-column product card grid matching the ASTRA design system
- Expandable product facts and structured catalogue evidence
- One-click 'Ask ASTRA about this item' integration with the Shopping Chat
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import streamlit as st

if TYPE_CHECKING:
    from .ui_service import ChatService

POPULAR_CATEGORIES = [
    "All Categories",
    "Women",
    "Clothing",
    "Men",
    "Shoes",
    "Jewelry",
    "Accessories",
    "T-Shirts",
    "Tops, Tees & Blouses",
    "Athletic",
    "Active",
    "Sandals",
    "Dresses",
    "Shirts",
    "Girls",
    "Boys",
    "Earrings",
    "Watches",
    "Hats & Caps",
    "Necklaces",
    "Handbags & Wallets",
    "Boots",
    "Fashion Sneakers",
    "Luggage & Travel Gear",
    "Running",
    "Flats",
]


def product_image_url(value: object) -> str | None:
    """Validate image URL safely to prevent XSS or broken asset loading."""
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in {"http", "https"} and parsed.hostname else None
    except ValueError:
        return None


def render_catalogue_browser(service: ChatService, show_images: bool) -> None:
    """Render the full-width catalogue exploration page in the existing ASTRA design style."""
    st.caption("PRODUCT CATALOGUE · 50,000 VERIFIED ITEMS")
    st.header("🛍️ Product Catalogue")
    st.caption(
        "Explore and scroll through the frozen verified catalogue. Search by keyword, "
        "filter by category and price, and inspect verified product attributes."
    )

    # 1. Search & Filter Bar
    with st.container(border=True):
        col_search, col_cat, col_sort = st.columns([2.5, 1.5, 1.5])
        with col_search:
            search_query = st.text_input(
                "Search Catalogue",
                placeholder="Keywords: e.g. boots, black dress, running shoes...",
                key="catalog_search_query",
            )
        with col_cat:
            selected_cat = st.selectbox(
                "Category",
                POPULAR_CATEGORIES,
                key="catalog_category_select",
            )
        with col_sort:
            sort_options = {
                "default": "Relevance / Default",
                "price_asc": "Price: Low to High",
                "price_desc": "Price: High to Low",
                "rating_desc": "Highest Rated",
            }
            sort_by = st.selectbox(
                "Sort By",
                list(sort_options.keys()),
                format_func=sort_options.get,
                key="catalog_sort_select",
            )

        col_min, col_max, col_known, col_page_size = st.columns([1, 1, 1.2, 1.2])
        with col_min:
            min_price = st.number_input(
                "Min Price ($)",
                min_value=0.0,
                max_value=5000.0,
                value=0.0,
                step=5.0,
                key="catalog_min_price",
            )
        with col_max:
            max_price = st.number_input(
                "Max Price ($)",
                min_value=0.0,
                max_value=5000.0,
                value=0.0,
                step=10.0,
                key="catalog_max_price",
            )
        with col_known:
            st.write("")
            st.write("")
            price_known = st.checkbox(
                "Price-verified only",
                value=False,
                key="catalog_price_known",
            )
        with col_page_size:
            page_size = st.selectbox(
                "Items Per Page",
                [12, 24, 48, 96],
                index=1,
                key="catalog_page_size",
            )

    # 2. Reset Page If Filter Changed
    filter_sig = f"{search_query}|{selected_cat}|{sort_by}|{min_price}|{max_price}|{price_known}|{page_size}"
    if st.session_state.get("last_catalog_filter_sig") != filter_sig:
        st.session_state["last_catalog_filter_sig"] = filter_sig
        st.session_state["catalog_page"] = 1

    current_page = st.session_state.get("catalog_page", 1)
    offset = (current_page - 1) * page_size

    # 3. Query Backend
    try:
        data = service.browse_catalogue(
            query=search_query,
            category=selected_cat if selected_cat != "All Categories" else None,
            min_price=float(min_price) if min_price > 0 else None,
            max_price=float(max_price) if max_price > 0 else None,
            price_known_only=price_known,
            sort_by=sort_by,
            limit=page_size,
            offset=offset,
        )
    except Exception as exc:
        st.error(f"Could not load catalogue products: {exc}")
        return

    total_count = data["total_count"]
    total_pages = max(1, math.ceil(total_count / page_size)) if total_count > 0 else 1
    if current_page > total_pages:
        current_page = 1
        st.session_state["catalog_page"] = 1
        offset = 0

    products = data.get("products", [])

    # 4. Results Header & Top Pagination
    st.divider()
    col_summary, col_pag = st.columns([2, 1])
    with col_summary:
        if total_count > 0:
            start_num = offset + 1
            end_num = min(total_count, offset + len(products))
            st.markdown(
                f"**Found {total_count:,} products** · Showing items **{start_num}–{end_num}** (Page {current_page} of {total_pages})"
            )
        else:
            st.markdown("**0 products found** matching the selected filters.")

    with col_pag:
        col_p1, col_p_label, col_p2 = st.columns([1, 1.5, 1])
        with col_p1:
            if st.button(
                "◀",
                disabled=(current_page <= 1),
                key="catalog_top_prev",
                help="Previous page",
            ):
                st.session_state["catalog_page"] = max(1, current_page - 1)
                st.rerun()
        with col_p_label:
            st.markdown(
                f"<div style='text-align: center; padding-top: 5px; font-size: 0.9em;'>"
                f"Page <b>{current_page}</b> / <b>{total_pages}</b></div>",
                unsafe_allow_html=True,
            )
        with col_p2:
            if st.button(
                "▶",
                disabled=(current_page >= total_pages),
                key="catalog_top_next",
                help="Next page",
            ):
                st.session_state["catalog_page"] = min(total_pages, current_page + 1)
                st.rerun()

    if not products:
        st.info(
            "No products match your criteria. Try relaxing your search terms or expanding the price range."
        )
        return

    # 5. Product Grid (3 Columns)
    cols_per_row = 3
    for i in range(0, len(products), cols_per_row):
        batch = products[i : i + cols_per_row]
        cols = st.columns(cols_per_row)
        for col, prod in zip(cols, batch, strict=False):
            with col, st.container(border=True):
                url = product_image_url(prod.get("image_url"))
                if show_images:
                    if url:
                        st.image(
                            url,
                            width="stretch",
                            alt=prod.get("title", "Product image"),
                        )
                    else:
                        st.caption("◇ Image unavailable")

                title = prod.get("title") or "Untitled Product"
                st.text(title[:115] + ("…" if len(title) > 115 else ""))

                facts = prod.get("facts") or {}
                price = facts.get("price")
                st.markdown(
                    f"**USD {price:.2f}**" if price is not None else "**Price unknown**"
                )

                # Attributes (Color, Material, Brand)
                attributes = []
                if facts.get("brand"):
                    attributes.append(f"Brand: {facts['brand']}")
                if facts.get("color"):
                    attributes.append(f"Color: {facts['color']}")
                if facts.get("material"):
                    attributes.append(f"Material: {facts['material']}")
                if attributes:
                    st.caption(" · ".join(attributes))

                # Rating
                rating = facts.get("rating")
                rating_cnt = facts.get("rating_count")
                if rating is not None:
                    cnt_str = f" ({int(rating_cnt):,} reviews)" if rating_cnt else ""
                    st.caption(f"⭐ {rating:.1f}{cnt_str}")

                # Categories
                cats = [
                    c
                    for c in prod.get("categories", [])
                    if c != "Clothing, Shoes & Jewelry"
                ]
                if cats:
                    st.caption(" · ".join(cats[:3]))

                # Details Expander
                with st.expander("Product details"):
                    st.text(title)
                    st.text("Product ID: " + prod["id"])
                    st.json(
                        {
                            "facts": facts,
                            "categories": prod.get("categories", []),
                            "evidence": prod.get("evidence", {}),
                        }
                    )

                # Quick action: Ask ASTRA about this product
                if st.button(
                    "💬 Ask ASTRA about this item",
                    key=f"cat_ask_{prod['id']}_{i}",
                    use_container_width=True,
                    help="Pre-fills a shopping inquiry for this product into the Shopping Chat.",
                ):
                    st.session_state["starter"] = (
                        f"Tell me about product {prod['id']}: {title[:80]}"
                    )
                    st.success(
                        "✓ Added to chat! Click the '💬 Shopping Chat' tab to continue."
                    )

    # 6. Bottom Pagination
    st.divider()
    b_col1, b_col2, b_col3 = st.columns([1, 2, 1])
    with b_col1:
        if st.button(
            "⬅️ Previous Page", disabled=(current_page <= 1), key="catalog_bot_prev"
        ):
            st.session_state["catalog_page"] = max(1, current_page - 1)
            st.rerun()
    with b_col2:
        st.markdown(
            f"<div style='text-align: center; padding-top: 5px;'>"
            f"Showing items <b>{offset + 1}–{min(total_count, offset + len(products))}</b> of <b>{total_count:,}</b> "
            f"(Page <b>{current_page}</b> of <b>{total_pages}</b>)</div>",
            unsafe_allow_html=True,
        )
    with b_col3:
        if st.button(
            "Next Page ➡️",
            disabled=(current_page >= total_pages),
            key="catalog_bot_next",
        ):
            st.session_state["catalog_page"] = min(total_pages, current_page + 1)
            st.rerun()
