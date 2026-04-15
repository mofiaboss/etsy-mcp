# Workflows — The Pure Primitive Proof

This document is the proof that etsy-mcp's pure-primitive architecture is sufficient for real seller workflows. Every example below is a complete end-to-end LLM-driven flow that uses **only the primitive tools** the MCP exposes. There is no scoring tool, no SEO heuristic, no tag generator, no "AI search readiness" judgment baked into any tool. Every reasoning step happens inside the model.

If you are tempted to file a feature request for a composite "do everything" tool, walk through these examples first. The answer is almost always: "Claude can already do this with the existing primitives — and the result is better because Claude can adapt as Etsy's algorithms and your business evolve."

---

## Example 1 — Bulk-import 5 Printful t-shirts with winning SEO tags

**User request to Claude:**

> "I just designed 5 new graphic t-shirts on Printful — punny pop-culture stuff. Pull the top-performing competitor listings in 'graphic t-shirt', figure out which tags are actually winning right now, mine the buyer reviews for vocabulary I'm missing, then import all 5 with the strongest tags you can find."

**Claude's tool sequence (pure primitives only):**

1. **Discover competitors**
   ```
   etsy_listings_search_active(
       keywords="graphic t-shirt funny pun",
       limit=20,
       sort_on="score",
       sort_order="desc"
   )
   ```
   Returns top 20 listings sorted by Etsy's relevance score. Claude inspects titles, tags, view counts, and favorers.

2. **Read full data for the top 5 competitors**
   ```
   etsy_listings_list_by_ids(listing_ids=[12345, 23456, 34567, 45678, 56789])
   ```
   Returns complete tag arrays, materials, taxonomy IDs, and full descriptions for each. Claude now sees exactly which tags are appearing on the highest-ranking listings.

3. **Walk the seller taxonomy** to find the right category and required attributes
   ```
   etsy_seller_taxonomy_get_buyer_taxonomy_nodes()
   etsy_seller_taxonomy_get_properties_by_taxonomy_id(taxonomy_id=1234)
   ```
   Claude now knows which `taxonomy_id` to use and which property attributes (e.g., `Primary color`, `Sizing`, `Style`) Etsy will require.

4. **Mine buyer vocabulary from the top listings' reviews**
   ```
   etsy_reviews_list_by_listing(listing_id=12345, limit=50)
   etsy_reviews_list_by_listing(listing_id=23456, limit=50)
   ```
   Reading actual buyer reviews tells Claude what words real shoppers use to describe these products — which words may differ from the seller's own vocabulary. This is a goldmine for tag selection.

5. **Reason about tags** — entirely inside Claude's context window. No tool call. Claude weighs the competitor tag overlap, the buyer vocabulary, the user's product names, and Etsy's 13-tag-per-listing limit. It picks the best 13 tags per listing and decides which are shared vs. unique per design.

6. **Apply via the bulk primitive**
   ```
   etsy_listings_bulk_create_from_template(
       shop_id=98765,
       template={
           "title_template": "{product_name} Funny Pop Culture Graphic T-Shirt | Unisex Cotton Tee",
           "description_template": "...",
           "taxonomy_id": 1234,
           "who_made": "i_did",
           "when_made": "made_to_order",
           "is_supply": false,
           "price": 24.99,
           "quantity": 999,
           "shipping_profile_id": 11111,
       },
       items=[
           {"product_name": "Schrodinger's Coffee", "tags": [...], "image_urls": [...]},
           {"product_name": "Pineapple on Pizza Defender", "tags": [...], "image_urls": [...]},
           ...
       ]
   )
   ```

   The bulk primitive iterates with per-item error isolation, applies the rate limiter automatically, and returns a per-item success/failure report. It executes the decisions Claude already made — it makes none of its own.

**What did the MCP contribute?** Exactly the data Claude asked for, in the shape Claude needed. Zero opinions on what makes a "good" tag.

**What would have happened with a composite `seo_score_listing` tool?** The heuristic would either match Claude's reasoning (in which case it adds nothing) or differ (in which case it overrides Claude's better judgment). It would also rot when Etsy's algorithm changes.

---

## Example 2 — Refresh SEO on 20 existing listings for AI search

**User request to Claude:**

> "AI shopping is taking over. I want to update the descriptions and tags on my 20 oldest listings so they read well to ChatGPT shopping mode and Claude's product recommendations. Don't touch the titles or prices — just descriptions and tags."

**Claude's tool sequence:**

1. **Read all current shop listings**
   ```
   etsy_listings_list_by_shop(shop_id=98765, state="active", limit=100, sort_on="created", sort_order="asc")
   ```
   Returns the 20 oldest active listings with full field data.

2. **Inspect each listing's current state**

   No tool call needed — Claude already has the full data from step 1. It walks each listing in its context window, identifying ones with:
   - Sparse descriptions (< 200 chars)
   - Tags that read like SEO spam from 2018 ("best gift for her", "free shipping", "etsy")
   - No structured product specs in the description

3. **Generate new content** — entirely inside Claude. No tool call.

   For each listing, Claude rewrites the description in a structured, conversational format that AI shopping assistants can parse: clear product name, bullet-point specs, materials, dimensions, care instructions, intended use cases. It picks new tags that emphasize natural-language phrases ("cozy reading nook lamp" instead of "lamp gift mom").

4. **Preview the changes before applying**

   ```
   etsy_listings_bulk_update_from_template(
       shop_id=98765,
       updates=[
           {"listing_id": 11111, "tags": [...], "description": "..."},
           {"listing_id": 22222, "tags": [...], "description": "..."},
           ...
       ],
       confirm=False
   )
   ```

   The MCP returns a preview envelope showing the per-listing diff: current tags vs proposed, current description vs proposed. Claude shows this to the user.

5. **User approves, Claude applies**

   ```
   etsy_listings_bulk_update_from_template(..., confirm=True)
   ```

   The bulk primitive uses fetch-merge-put per listing — the existing title, price, image set, and inventory are preserved. Only the fields Claude specified are touched. Per-item error isolation: if listing 17 fails, the other 19 still succeed.

**What did the MCP contribute?** Read access, a preview-then-confirm flow, and a bulk write primitive. Zero opinions on what good AI-search-friendly content looks like — that judgment belongs to the model.

---

## Example 3 — Audit and fix image alt_text across the entire shop

**User request to Claude:**

> "Run an alt_text audit on every product image in my shop. For any image missing alt_text, generate a description from the image itself and apply it. Accessibility matters and I've been lazy."

**Claude's tool sequence:**

1. **List all active listings**
   ```
   etsy_listings_list_by_shop(shop_id=98765, state="active", limit=200)
   ```

2. **For each listing, list its images**
   ```
   etsy_listing_images_list(shop_id=98765, listing_id=11111)
   etsy_listing_images_list(shop_id=98765, listing_id=22222)
   ...
   ```

   Each image record includes `alt_text` (string or null) and a public `url_fullxfull`. Claude builds a working set of `(listing_id, image_id, image_url)` tuples where `alt_text` is null or empty.

3. **Describe each image** — entirely inside Claude's vision capability. No tool call.

   For each image URL in the working set, Claude fetches the image (via its own multimodal vision, NOT via an MCP tool — the MCP doesn't do image processing) and writes a 1-2 sentence accessible description: what the product is, key visual features, color, context. This is reasoning the model is uniquely good at; baking it into the MCP would lock in one model's image-understanding capability.

4. **Preview the bulk update**

   ```
   etsy_listing_images_bulk_update_alt_text(
       shop_id=98765,
       updates=[
           {"listing_id": 11111, "listing_image_id": 111, "alt_text": "Cream-colored ceramic mug with hand-painted blue floral pattern, photographed on a wooden table."},
           {"listing_id": 11111, "listing_image_id": 112, "alt_text": "Top-down view of the same mug filled with coffee, showing the interior glaze."},
           ...
       ],
       confirm=False
   )
   ```

   Preview shows the count of images that will be updated and a sample of the proposed alt_text values.

5. **User approves, Claude applies**

   ```
   etsy_listing_images_bulk_update_alt_text(..., confirm=True)
   ```

   Bulk primitive iterates with rate limiting and per-item error isolation. Returns a per-image success/failure report.

**What did the MCP contribute?** A way to list images, a way to bulk-update alt_text. The image understanding — the actual hard part — happens in Claude's vision model. There is no `image_describe` tool in the MCP, and there shouldn't be: that would either commit the MCP to a specific vision model (locking out future improvements) or duplicate functionality the LLM already has natively.

---

## The pattern

Every workflow above looks the same:

1. **Discover** with read primitives (`*_list_*`, `*_search_*`, `*_get_*`)
2. **Reason** inside the model (this is the part that matters; the MCP contributes nothing here)
3. **Preview** with `confirm=False` on the mutation
4. **Apply** with `confirm=True` — usually via a bulk primitive for rate-limit efficiency

The MCP is the boring part. The model is the smart part. **This is on purpose.** If you find yourself wishing for a tool that "just does the SEO thing" — that wish is the antibody. The right answer is: trust the model to do the SEO thing using the primitives it already has, and your workflow will continue to work as both the model and Etsy improve.

## Every step uses pure primitives. Claude provides all the reasoning.

This is not a limitation. It is the architecture.
