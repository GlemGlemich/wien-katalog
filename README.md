# Price Tag — Vienna grocery catalogue

A local catalogue of products, prices and current promotional leaflets from **SPAR, BILLA, HOFER, PENNY and Lidl Austria**. Browse saved prices, filter products, compare stores and inspect offers extracted from official Flugblatt PDFs. Shopping lists and route planning are not implemented.

## Getting started

Requires **Python 3.10 or later**. Install the PDF extraction dependencies:

```sh
python -m pip install -r requirements.txt
python app.py --open
```

On Windows, you can also double-click **`Запустить каталог.cmd`** (the catalogue launcher). It uses the bundled Codex Python runtime when available, otherwise the `python` command. Keep the server window open. The app runs at [http://127.0.0.1:8765](http://127.0.0.1:8765).

Click **Download prices** to read all five sources. Selecting a store limits the update to that store. Downloads take several minutes; products appear as they arrive and are saved in `data/catalog.sqlite3` between sessions. Internet access is needed for new prices and images. Saved names and prices remain available offline and without the PDF extraction dependency.

To refresh prices on startup:

```sh
python app.py --open --refresh
```

## Interface language

Use the **Русский / English** selector in the top bar. Russian is the default. Your choice is saved in this browser and restored on the next visit. If browser storage is unavailable, switching still works for the current page.

Navigation, filters, selections, comparisons, leaflet controls, statuses, application messages and accessible labels are translated. Number and date formatting follows the language; dates remain in the **Europe/Vienna** time zone and prices in **EUR**. Switching keeps your section, store, search and filters and does not download prices from retailer websites.

Original retailer product names, categories and promotional wording remain as published, usually in German. App-generated purchase conditions are translated. Translations live in `static/i18n.js`; no translation service, AI API or tokens are required.

## Catalogue and product selections

The main catalogue groups products into **Drinks**, **Alcohol**, **Sweets and snacks**, **Fruit and vegetables**, **Dairy and eggs**, **Meat and fish**, **Bread and pantry**, **Ready meals** and **Other**. Categories combine with store, search, validity and sorting filters. Counts reflect active filters. The original retailer category appears under the product name.

**Product selections** contains five overlapping selections:

- **Sweet drinks:** cola, juices, soft drinks, iced tea and energy drinks, including Zero versions.
- **Protein products:** names or retailer categories marked Protein, High Protein, Eiweiß or Whey. Protein content is not calculated. Pet food and cosmetics are excluded.
- **Milk:** plain, flavoured and plant-based drinks, with lactose-free labelling, fat content and storage filters: Frisch, Länger frisch / ESL and H-Milch. Combine filters, for example Laktosefrei + Vollmilch. Missing lactose-free labelling does not prove that a product contains lactose. Plant-based drinks are not assigned cow's-milk fat categories.
- **Meat and fish:** chicken, pork, beef, turkey, veal, lamb, other poultry, game, mixed meat, fish and seafood. Refine by cuts, mince, sausages/smoked products or prepared products. Unknown types remain unspecified. Plant substitutes and meat-flavoured products are excluded.
- **Alcohol:** beer/cider, wine, sparkling wine, spirits/liqueurs and cocktails/mixes. Alkoholfrei, 0,0 and Entalkoholisiert versions remain in Drinks. Sweets, flavourings, cosmetics and other non-drinks with alcohol-related names are excluded. Alcohol strength is not inferred.

Detailed filters also appear in the relevant main categories. Counts consider the other filters; unavailable combinations are disabled. **Reset filters** clears search, discounts, refinements and quantity filters and returns validity to **Valid today**, keeping your selection and store. Catalogue and selection filters are retained separately when switching tabs.

Selections show the latest saved prices valid today, excluding future and expired offers. Recently checked products appear first by default. Rows retain check times and regular, discounted, loyalty and multipack conditions. Opening a selection does not fetch retailer prices; use **Refresh prices** for that.

Classification uses retailer categories first, then product names when necessary. Unknown attributes are not guessed. Reclassification does not change price check times. Some classification errors are possible.

## Reading and comparing prices

Choose **Compare prices by → Per 1 kg / Per 1 l** to highlight the unit price and sort from lowest to highest. The original website price for the pack or stated quantity stays visible. Kilograms and litres are never mixed; products without a known price for the chosen unit are excluded from that mode.

**Pack weight / volume** shows sizes and counts, such as 250 g, 500 g, 1 kg or 1 l. Sizes refer to the entire pack: 2 × 250 g counts as 500 g. Variable-weight products are separate, even when priced per kg. Ranges, alternative sizes such as 120/150 g and approximate weights are not presented as exact sizes.

The retailer's published unit price takes priority. Prices per 100 g or 500 ml are normalised to per kg or litre, preserving the retailer's basis, including drained weight where relevant. Otherwise, calculation requires an unambiguous fixed pack size. Unknown weight is not inferred from price. A 1+1 discount is not applied twice to an already discounted price.

**Compare stores** shows the cheapest matching saved offer from each of the five stores per kg or litre. It uses category/selection, search, subtype, size and discount filters across all stores, even when one store is selected in the sidebar. It considers all matching saved products, not just the current page, and excludes future and expired offers.

The lowest main price is highlighted; other rows show the difference. Separate loyalty prices appear alongside and do not determine the ordering. Their unit prices are approximate, scaled in proportion to the main price. Brands and products can differ: this is not barcode matching. Each result includes its name, quantity, check time and source. No matching saved result does not imply that a store has no such product in stock. Filter changes update an open comparison.

**Discounted products only** includes confirmed reductions: a main price below the regular price, a multipack price below the single-item price, or a loyalty price below the main price. Conditions stay visible.

- Conditional prices include their conditions and single-item prices when available.
- jö and Lidl Plus prices do not replace the main price.
- Original quantities remain visible; normalised prices are shown separately.
- A historical 30-day low is not treated as the regular price.
- Future and expired offers are retained but excluded from **Valid today**.
- Missing expiry dates are not invented. Checks older than 24 hours are marked as stale.
- Check times use Vienna time. Branch-level stock is not verified.

## Offers · Flugblatt

**Offers → Products and prices** lists offers extracted from official PDFs. Rows show the store, size, price, conditions such as 1+1 or minimum quantity, dates and original-page links. Regular and Lidl Plus offers are separate. **Store leaflets** contains covers and source links. The sidebar store filter applies to both views.

All categories are shown initially. Choose **Drinks → Cola**, **Juices and nectars**, **Soft drinks**, **Protein drinks** or another group, or search by product name. Russian aliases are also supported. Exclude loyalty cards/coupons or limit the quantity you are willing to buy. A per-litre best-offer comparison appears for a drink group when at least two stores have matching offers. It compares extracted offers, not every product in Vienna; brands, flavours and ingredients may differ.

Offer previews are images of original PDF pages generated locally from downloaded PDFs and cached. They are not substitute product photos. Clicking opens the original source.

**Product selections** also shows up to three matching leaflet offers and a link to all results, using the selection, store and search. These are in-store offers with their own conditions; they do not replace online prices in the table. Other table filters apply to the online catalogue only. For example, an online NÖM PRO price can differ from a leaflet's 1+1 offer.

### Coverage and limitations

As documented on **3 October 2026**, extraction covers some products from BILLA, HOFER, Lidl and SPAR Vienna PDFs. PENNY's viewer does not provide a usable PDF; its cover and original link remain available. Full extraction from all five stores is not guaranteed. Scans without a text layer are not recognised. Ambiguous layouts, mixed sizes, approximate weights and complex alternative conditions are skipped and counted in coverage status. Online catalogue prices are not substituted for missing leaflet offers.

Printed prices such as “bei 6 je” already include the discount and are not halved again. A printed €0.99 when buying six packs gives an estimated total of €5.94. Rounding may cause a few cents' difference at checkout. Unit prices use the printed price; Pfand deposits are excluded. Original conditions remain accessible.

**Refresh offers** checks editions and extracts products without reloading online catalogues. Initial PDF downloads may take several minutes and hundreds of megabytes. PDFs and extracted text are cached in `data/leaflet-cache`; an edition's PDF is reused for up to six hours. With the offers tab open, sources are checked automatically when the last attempt was over six hours ago. Nothing updates while the program is closed. Failed reads preserve saved offers and their successful check times.

Validity comes from official offer dates rather than file publication dates. Shorter page-specific periods are respected, including HOFER weekend offers. Future and expired offers are hidden using Vienna's local date even without a refresh. BILLA Sunday and nationwide Austrian public-holiday exclusions are applied when stated in the leaflet.

Official sources: [SPAR](https://www.spar.at/aktionen), [BILLA](https://www.billa.at/unsere-aktionen/flugblatt), [HOFER](https://www.hofer.at/flugblatt), [PENNY](https://www.penny.at/angebote/flugblaetter), [Lidl](https://www.lidl.at/c/flugblatt/s10012330). SPAR and BILLA use Vienna editions; other stores use Austrian editions. PENNY opens on its official website.

**SPAR limitation recorded on 2 October 2026:** the edition listing returned HTTP 403. Previously discovered Vienna links are retained in `data/flyer-sources.json`. When the listing is unavailable, the app checks known editions and warns that new editions may be missing. It does not invent future links or claim a complete listing refresh. Expired editions are hidden; the official website remains linked in source checks.

## Data sources

Importers traverse all pages of their available published catalogue. Saved fields include product ID, name, store, quantity, price, previous price, conditions, validity, image, source URL and check time. Prices are stored as integer euro cents for sorting.

| Store | Source | Coverage boundary |
| --- | --- | --- |
| SPAR | Public search catalogue, all pages | Online range; independent branches may use different prices |
| BILLA | Public BILLA Online Shop catalogue, all pages | No delivery address selected; in-store prices may differ |
| HOFER | `/produkte?page=N` | Only products published on the website |
| PENNY | Public product catalogue, all pages | Mainly offers with validity dates |
| Lidl | `/q/search?fetchSize=60&offset=N` | Mainly weekly offers, without a selected branch |

“All products” means all available source items with published prices, not guaranteed coverage of physical stores. Unpriced items are counted separately in source status. Products across stores are not automatically merged. Published non-food items are included.

## Reliability and local operation

The **Python process** needs network access. When internet access is blocked, the browser can still show saved products while updates fail. Allow network access and restart the server, or launch the Windows script normally. The app distinguishes blocked access from an unavailable network, displays the cause and avoids retrying explicitly blocked requests. Transient connection/server failures receive limited retries. Failed attempts do not change saved prices or successful check times.

Retailer requests run locally, avoiding browser CORS restrictions. The server binds to `127.0.0.1`. Updates require a random local session token, SQL queries are parameterised and TLS certificates are verified. Store failures do not erase saved data. Incomplete imports preserve previous products; missing items are hidden only after a complete successful import.

Retailer interface changes may require updates to `parsers.py` or `sources.py`. Errors are shown explicitly; sample prices are never presented as real prices.

## Development and checks

Run the Python regression tests:

```sh
python -m unittest -v test_catalog test_product_details test_quantities test_alcohol test_network test_flyers test_offers
```

These cover conditional prices, weights, validity, combined filters, comparisons and data preservation after network failures. Extraction tests use real-page text and coordinates without network requests.

Run the language checks with Node.js:

```sh
node --test test_i18n.cjs
```

After application changes, run appropriate checks, commit and push to `origin/main`. Do not commit the local database, leaflet cache, update state, credentials or secrets. A fresh checkout fills its catalogue after the first price update.
