# Local TechJam catalogue inventory

Catalogue SHA-256: `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`. Read-only index source hash verified.
50,000 rows; 800 exact leaf labels. Same labels across taxonomy paths are combined.

Generated with `.venv/bin/python experiments/longitudinal/catalogue_inventory.py`.
Counts describe parent products, not selectable variants or current availability.
Usable price means the existing oracle's positive finite price. Color/material coverage
counts only priced rows with structured detail fields accepted by `raw_facts`; titles
and images are never used to infer attributes. Values shown are the three most frequent
verbatim structured values, with counts. Missing fields stay unknown.

Reporting buckets are heuristic taxonomy summaries only; they do not alter evaluation.
The residual bucket includes jewelry, watches, accessories, luggage gear and unclassified
leaves. Mixed-path leaf labels can appear in several buckets in the detailed table.

| Reporting bucket | Rows |
| --- | ---: |
| Bags | 1387 |
| Clothing | 21637 |
| Footwear | 11689 |
| Jewelry/accessories/other | 15287 |

| Exact leaf | Buckets | Rows | Priced | Color known | Material known | Color examples | Material examples |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| $50 and Under Backpacks | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| 100% Plus & Featured Brands | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| 100% Plus (No Title Match) | Jewelry/accessories/other | 6 | 0 | 0 | 0 | — | — |
| 20% Off $100 Women's & Men's | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| 20% Off $80 Women's Shoes & Handbags | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| 20% Off President's Day Savings | Kids & Baby | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| 20% Off Prime Members Exclusive | Kids | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| 20% Off Prime Members Exclusive | Men | Jewelry/accessories/other | 2 | 1 | 0 | 0 | — | — |
| 25% Off Harley Davidson Footwear | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| 4+ Stars: Clothes, Shoes and Jewelry | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| 4th of July Up to 60% Off | Jewelry/accessories/other | 3 | 0 | 0 | 0 | — | — |
| Accessories | Clothing, Jewelry/accessories/other | 180 | 63 | 10 | 6 | Multicolor (1); Multicam (1); Silver (1) | Cotton (1); Rhinestone (1); Silk (1) |
| Accessory Sets | Jewelry/accessories/other | 22 | 13 | 0 | 0 | — | — |
| Active | Clothing, Jewelry/accessories/other | 62 | 6 | 0 | 0 | — | — |
| Active & Performance | Clothing | 11 | 0 | 0 | 0 | — | — |
| Active Base Layers | Clothing | 49 | 9 | 2 | 2 | Black (1); 328 Cloudberry (1) | Wool (1); Polypropylene, Merino Wool (1) |
| Active Dresses | Clothing | 6 | 1 | 0 | 0 | — | — |
| Active Hoodies | Clothing | 89 | 26 | 2 | 2 | Black (1); Black/Black/White (1) | Cotton (1); 80% Cotton/20% Polyester (1) |
| Active Pants | Clothing | 149 | 14 | 0 | 0 | — | — |
| Active Shirts & Tees | Clothing | 263 | 34 | 2 | 2 | Turq Multi (1); Black (1) | Nylon (1); Polyester (1) |
| Active Shorts | Clothing | 294 | 53 | 0 | 0 | — | — |
| Active Skirts | Clothing | 22 | 4 | 0 | 0 | — | — |
| Active Skorts | Clothing | 16 | 3 | 0 | 0 | — | — |
| Active Sweatshirts | Clothing | 57 | 13 | 0 | 0 | — | — |
| Active Sweatsuits | Clothing | 18 | 5 | 0 | 0 | — | — |
| Active Tracksuits | Clothing | 44 | 20 | 1 | 1 | Sky Blue-1 (1) | 95% Polyester,5% Spandex (1) |
| Active Underwear | Clothing | 7 | 0 | 0 | 0 | — | — |
| Active Vests | Clothing | 3 | 0 | 0 | 0 | — | — |
| Adhesive Bras | Clothing | 8 | 1 | 0 | 0 | — | — |
| Adult Apparel | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Amazon Fashion 3 | Jewelry/accessories/other | 9 | 1 | 0 | 0 | — | — |
| Amazon Fashion Sales & Deals | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Amazon Private and Exclusive Brands | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| American Football | Clothing | 1 | 0 | 0 | 0 | — | — |
| Ankle & Bootie | Footwear | 382 | 39 | 1 | 0 | Taupe (1) | — |
| Anklets | Jewelry/accessories/other | 71 | 27 | 25 | 19 | Silver (5); Black (3); Gold (2) | Metal (9); Stone (2); Alloy (2) |
| Anniversary Rings | Jewelry/accessories/other | 3 | 1 | 0 | 0 | — | — |
| Anoraks | Clothing | 9 | 3 | 0 | 0 | — | — |
| Apparel and accessories Made in Italy | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Applique Patches | Clothing | 16 | 13 | 10 | 5 | White (2); Multi (1); Bigfoot (1) | Polyester (2); Polycotton (1); Plastic (1) |
| Aprons | Clothing | 10 | 7 | 0 | 0 | — | — |
| Arm Warmers | Jewelry/accessories/other | 11 | 3 | 0 | 0 | — | — |
| Associates top products | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Athletic | Footwear | 37 | 2 | 0 | 0 | — | — |
| Athletic & Outdoor | Footwear | 7 | 0 | 0 | 0 | — | — |
| Athletic Socks | Clothing | 276 | 80 | 2 | 1 | Varsity Red (650) / Black/Varsity Red (1); Black/White/(White) (1) | Polyester, Spandex (1) |
| Athletic Supporters | Clothing | 7 | 3 | 0 | 0 | — | — |
| BIBA End of Season Sale | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Baby | Jewelry/accessories/other | 7 | 3 | 0 | 0 | — | — |
| Baby Boys | Jewelry/accessories/other | 19 | 9 | 0 | 0 | — | — |
| Baby Boys Shoes Union | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Baby Boys' Swimwear | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Baby Dolls & Chemises | Clothing | 26 | 5 | 0 | 0 | — | — |
| Baby Girls | Jewelry/accessories/other | 17 | 8 | 0 | 0 | — | — |
| Baby Girls' Clothes Under $10 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Baby Girls' Outerwear | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Baby Girls' Swimwear | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Backpacking Boots | Footwear | 10 | 1 | 0 | 0 | — | — |
| Backpacks | Bags | 28 | 3 | 0 | 0 | — | — |
| Backpacks Under $25 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Backpacks Under $50 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Bags Made in Italy | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Balaclavas | Jewelry/accessories/other | 113 | 18 | 2 | 2 | Three Colors (1); Black (1) | Cotton (2) |
| Ball | Jewelry/accessories/other | 11 | 6 | 0 | 0 | — | — |
| Ballet | Footwear | 1 | 1 | 0 | 0 | — | — |
| Ballet & Dance | Footwear | 42 | 7 | 0 | 0 | — | — |
| Bandanas | Clothing | 33 | 9 | 1 | 1 | Blue (1) | Polyester (1) |
| Bands | Jewelry/accessories/other | 100 | 40 | 0 | 0 | — | — |
| Bangle | Jewelry/accessories/other | 139 | 52 | 40 | 40 | Silver (7); Gold (3); Shiny Silver (2) | Metal (15); Stainless Steel (3); Alloy (3) |
| Barbells | Jewelry/accessories/other | 83 | 36 | 0 | 0 | — | — |
| Base Layers & Compression | Clothing | 5 | 1 | 0 | 0 | — | — |
| Baseball | Clothing | 1 | 1 | 0 | 0 | — | — |
| Baseball & Softball | Footwear | 16 | 2 | 0 | 0 | — | — |
| Baseball Caps | Clothing, Jewelry/accessories/other | 385 | 135 | 2 | 2 | White (1); Buffalo Plaid (1) | Polyester, Mesh (1); Blend (1) |
| Basketball | Clothing, Footwear | 138 | 13 | 0 | 0 | — | — |
| Bead | Jewelry/accessories/other | 113 | 47 | 0 | 0 | — | — |
| Beanies & Knit Hats | Clothing | 12 | 3 | 0 | 0 | — | — |
| Belly Bands | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Belt Buckles | Clothing | 18 | 7 | 0 | 0 | — | — |
| Belts | Clothing, Jewelry/accessories/other | 260 | 86 | 4 | 3 | Endless Leather - Brown (1); 22 (1); Black (1) | Leather (1); Faux Leather (1); Nylon (1) |
| Berets | Jewelry/accessories/other | 10 | 6 | 0 | 0 | — | — |
| Bib Pants | Clothing | 3 | 0 | 0 | 0 | — | — |
| Bib Shorts | Clothing | 6 | 1 | 0 | 0 | — | — |
| Bibs | Clothing | 6 | 1 | 0 | 0 | — | — |
| Big Kid Size 7 | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Big Kid Size 8 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Bikinis | Clothing | 37 | 7 | 0 | 0 | — | — |
| Birthstone Jewelry Gifts | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Blanket Sleepers | Clothing | 26 | 3 | 0 | 0 | — | — |
| Blazers | Clothing | 78 | 17 | 0 | 0 | — | — |
| Bloomers | Clothing | 3 | 1 | 0 | 0 | — | — |
| Bloomers, Diaper Covers & Underwear | Clothing | 3 | 0 | 0 | 0 | — | — |
| Blouses & Button-Down Shirts | Clothing, Jewelry/accessories/other | 691 | 124 | 0 | 0 | — | — |
| Board Shorts | Clothing | 82 | 13 | 0 | 0 | — | — |
| Body Chains | Jewelry/accessories/other | 31 | 18 | 1 | 0 | Gold (1) | — |
| Bodystockings | Clothing | 2 | 0 | 0 | 0 | — | — |
| Bodysuits | Clothing, Jewelry/accessories/other | 156 | 60 | 1 | 3 | Pink (1) | Cotton (3) |
| Bolo Ties | Jewelry/accessories/other | 6 | 2 | 0 | 0 | — | — |
| Bomber Hats | Jewelry/accessories/other | 8 | 5 | 0 | 0 | — | — |
| Boot Shop | Jewelry/accessories/other | 3 | 0 | 0 | 0 | — | — |
| Boots | Footwear, Jewelry/accessories/other | 268 | 18 | 0 | 0 | — | — |
| Bottoms | Clothing, Jewelry/accessories/other | 168 | 40 | 1 | 1 | Gold (1) | metal (1) |
| Bow Ties | Clothing, Jewelry/accessories/other | 33 | 14 | 0 | 0 | — | — |
| Bowling | Footwear | 20 | 0 | 0 | 0 | — | — |
| Boxer Briefs | Clothing | 133 | 24 | 0 | 0 | — | — |
| Boxers | Clothing | 35 | 6 | 0 | 0 | — | — |
| Boy Shorts | Clothing | 28 | 10 | 0 | 0 | — | — |
| Boys | Clothing, Jewelry/accessories/other | 29 | 5 | 0 | 0 | — | — |
| Boys Active | Jewelry/accessories/other | 4 | 2 | 0 | 0 | — | — |
| Boys Athletic | Jewelry/accessories/other | 6 | 0 | 0 | 0 | — | — |
| Boys Sneakers (fs, no puma) | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Boys Sneakers (no fs) | Jewelry/accessories/other | 2 | 1 | 0 | 0 | — | — |
| Boys' Character Shop | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Boys' Swimwear | Jewelry/accessories/other | 6 | 2 | 0 | 0 | — | — |
| Bra Extenders | Clothing | 5 | 3 | 2 | 1 | Random (1); Black+red+skincolor (1) | Nylon (1) |
| Bracelets | Jewelry/accessories/other | 146 | 39 | 25 | 31 | Silver (5); Black (3); Red (3) | Metal (6); Stainless Steel (4); Wood (2) |
| Bras | Clothing | 8 | 1 | 0 | 0 | — | — |
| Breast Petals | Clothing | 5 | 3 | 3 | 3 | Champagne (1); Dark Skin Tone (1); Complexion (1) | Silicone (3) |
| Breeches | Clothing | 8 | 3 | 0 | 0 | — | — |
| Bridal Sets | Jewelry/accessories/other | 20 | 7 | 0 | 0 | — | — |
| Bridal Veils | Jewelry/accessories/other | 8 | 2 | 0 | 0 | — | — |
| Briefcases | Bags | 24 | 4 | 2 | 2 | Saddle (1); Black (1) | Leather (2) |
| Briefs | Clothing | 113 | 32 | 0 | 0 | — | — |
| Brooches & Pins | Jewelry/accessories/other | 114 | 70 | 4 | 2 | Dark Blue (1); Red (1); 12 Pins (1) | Shinny gold (1); Silver, Copper (1) |
| Bucket Hats | Jewelry/accessories/other | 21 | 8 | 0 | 0 | — | — |
| Build Your Wardrobe: Cardigans for Her | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Bulk Buying & Case Packs | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Business Card Cases | Jewelry/accessories/other | 21 | 4 | 4 | 3 | Black (2); Silver (1); silver (1) | Leather (1); Leather, Cotton (1); Metal (1) |
| Business Pricing & Quantity Discounts | Jewelry/accessories/other | 11 | 1 | 0 | 0 | — | — |
| Bustiers & Corsets | Clothing | 23 | 6 | 1 | 1 | Beige Breathable (1) | Rubber (1) |
| Button-Down & Dress Shirts | Clothing | 3 | 0 | 0 | 0 | — | — |
| Button-Down Shirts | Clothing | 31 | 9 | 1 | 1 | Cool Grey (1) | Polyester (1) |
| Buttons & Pins | Clothing | 66 | 45 | 2 | 1 | Blue (1); Chrome plated, enamel colors (1) | Brass (1) |
| Cabinets & Cases | Jewelry/accessories/other | 22 | 8 | 6 | 6 | Black (3); brown,silver (1); walnut (1) | Leather (2); Faux Leather, Wood, Stainless Steel (1); Ethylene Vinegar (1) |
| Calf Socks | Clothing | 52 | 18 | 0 | 0 | — | — |
| California Costumes | Jewelry/accessories/other | 2 | 2 | 0 | 0 | — | — |
| Camisoles & Tanks | Clothing | 37 | 15 | 0 | 0 | — | — |
| Caps | Clothing | 4 | 1 | 0 | 0 | — | — |
| Card & ID Cases | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Card Cases | Jewelry/accessories/other | 32 | 8 | 6 | 5 | Black (3); Black Marble (1); Brown (1) | Leather (2); Aluminum (1); Aluminum, Plastic, Metal (1) |
| Cardigan | Clothing | 8 | 3 | 0 | 0 | — | — |
| Cardigans | Clothing | 315 | 41 | 0 | 0 | — | — |
| Cargo | Clothing | 46 | 8 | 0 | 0 | — | — |
| Carry-Ons | Jewelry/accessories/other | 54 | 5 | 0 | 0 | — | — |
| Casual | Clothing, Jewelry/accessories/other | 1099 | 150 | 0 | 0 | — | — |
| Casual & Dress Socks | Clothing | 8 | 3 | 0 | 0 | — | — |
| Casual Button-Down Shirts | Clothing | 288 | 68 | 1 | 1 | Depth Charge (1) | Polyester, Spandex, Cotton (1) |
| Casual Daypacks | Bags | 176 | 39 | 4 | 3 | Black (2); Iron Grey (1); Natural / Oz Bound (1) | Polyester (1); Canvas (1); Synthetic (1) |
| Casual Dresses Under $50 | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Casual Jackets | Clothing | 46 | 11 | 0 | 0 | — | — |
| Cat T-Shirts | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Chains | Jewelry/accessories/other | 118 | 44 | 0 | 0 | — | — |
| Charm | Jewelry/accessories/other | 18 | 7 | 6 | 5 | Black (2); Gold (1); R (1) | Metal (2); rope (1); aolly (1) |
| Charm Bracelets | Jewelry/accessories/other | 15 | 3 | 1 | 1 | Black (1) | Metal (1) |
| Charms | Jewelry/accessories/other | 30 | 16 | 0 | 1 | — | Metal (1) |
| Charms & Charm Bracelets | Jewelry/accessories/other | 9 | 0 | 0 | 0 | — | — |
| Checkbook Covers | Jewelry/accessories/other | 9 | 6 | 3 | 4 | Antiqued Black (1); Blue,Green (1); Chocolate Brown (1) | Leather (2); Vinyl (1); Genuine Leather (1) |
| Chef Jackets | Clothing | 10 | 6 | 0 | 0 | — | — |
| Chef Pants | Clothing | 1 | 1 | 0 | 0 | — | — |
| Chelsea | Footwear, Jewelry/accessories/other | 183 | 31 | 0 | 0 | — | — |
| Chokers | Jewelry/accessories/other | 77 | 31 | 0 | 0 | — | — |
| Christening | Clothing | 1 | 0 | 0 | 0 | — | — |
| Chukka | Footwear, Jewelry/accessories/other | 108 | 8 | 0 | 0 | — | — |
| Civil Service | Clothing | 1 | 1 | 1 | 0 | Anodized (1) | — |
| Clasp | Jewelry/accessories/other | 16 | 9 | 0 | 0 | — | — |
| Cleaning & Care | Jewelry/accessories/other | 3 | 0 | 0 | 0 | — | — |
| Clearance | Jewelry/accessories/other | 11 | 0 | 0 | 0 | — | — |
| Climbing | Footwear | 17 | 3 | 0 | 0 | — | — |
| Clip-Ons | Jewelry/accessories/other | 23 | 8 | 0 | 0 | — | — |
| Clogs & Mules | Footwear | 38 | 2 | 0 | 0 | — | — |
| Clothing | Clothing | 423 | 57 | 3 | 2 | Black (2); Olive (1) | Wool Blend (1); 900D Polyester Ripstop With Pu Face Out Coating (1) |
| Clothing Coinstar Exclusive | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Clothing Outlet | Jewelry/accessories/other | 2 | 1 | 0 | 0 | — | — |
| Clothing Outlet for Rank | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Clothing Sets | Clothing | 17 | 3 | 0 | 0 | — | — |
| Club & Night Out | Clothing | 141 | 31 | 1 | 1 | Silver (1) | Polyester (1) |
| Clutches | Bags | 42 | 7 | 1 | 1 | Colorful (1) | fabric-and-leather (1) |
| Coats & Jackets under $75 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Coats, Jackets & Vests | Clothing, Jewelry/accessories/other | 22 | 4 | 0 | 0 | — | — |
| Cocktail | Clothing | 136 | 12 | 0 | 0 | — | — |
| Coin Purses & Pouches | Jewelry/accessories/other | 40 | 13 | 1 | 1 | English Saddle (1) | Leather (1) |
| Cold Weather | Jewelry/accessories/other | 3 | 0 | 0 | 0 | — | — |
| Cold Weather Gloves | Jewelry/accessories/other | 113 | 28 | 8 | 8 | Black (5); Black (001)/Pitch Gray (1); Black-Buckle (1) | Polyester (1); Leather (1); Polyester, Nylon (1) |
| Cold Weather Headbands | Jewelry/accessories/other | 12 | 7 | 6 | 6 | wintry white (1); Solid W/Faux Fur - White (1); Multicolor (1) | Polyester (2); Faux Fur (1); Acrylic (1) |
| Cold Weather Scarves | Jewelry/accessories/other | 7 | 0 | 0 | 0 | — | — |
| Cold Weather Scarves & Wraps | Jewelry/accessories/other | 42 | 7 | 0 | 0 | — | — |
| Collar Stays | Jewelry/accessories/other | 2 | 2 | 0 | 0 | — | — |
| Collars | Jewelry/accessories/other | 10 | 4 | 0 | 0 | — | — |
| Combat | Jewelry/accessories/other | 109 | 12 | 0 | 0 | — | — |
| Commuter Pass Cases | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Compression Arm Sleeves | Clothing | 1 | 1 | 0 | 0 | — | — |
| Compression Pants & Tights | Clothing | 61 | 7 | 0 | 0 | — | — |
| Compression Shorts | Clothing | 11 | 0 | 0 | 0 | — | — |
| Compression Socks | Clothing | 19 | 2 | 0 | 0 | — | — |
| Control Panties | Clothing | 24 | 8 | 0 | 0 | — | — |
| Costumes | Clothing, Jewelry/accessories/other | 470 | 185 | 5 | 5 | As Shown (1); White (1); Purple (1) | Leather, Plastic (1); plush (1); Polyester, Spandex (1) |
| Costumes & Accessories | Jewelry/accessories/other | 6 | 2 | 0 | 0 | — | — |
| Costumes & Cosplay Apparel | Jewelry/accessories/other | 2 | 2 | 0 | 0 | — | — |
| Cotton | Clothing | 28 | 6 | 0 | 0 | — | — |
| Cover-Up Sets | Clothing | 4 | 0 | 0 | 0 | — | — |
| Cover-Ups | Clothing | 163 | 32 | 0 | 0 | — | — |
| Cover-Ups & Wraps | Clothing | 5 | 1 | 0 | 0 | — | — |
| Cowboy Hats | Clothing, Jewelry/accessories/other | 29 | 13 | 0 | 0 | — | — |
| Cravats | Jewelry/accessories/other | 2 | 1 | 0 | 0 | — | — |
| Cross-Body Sling Bags | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Crossbody Bags | Bags | 271 | 40 | 1 | 0 | Cream (1) | — |
| Cuff | Jewelry/accessories/other | 101 | 32 | 25 | 23 | Silver (4); Black (3); Red (2) | Metal (8); Leather (4); Stainless Steel (3) |
| Cuff Links | Jewelry/accessories/other | 36 | 13 | 0 | 0 | — | — |
| Cuffs & Wraps | Jewelry/accessories/other | 38 | 18 | 0 | 0 | — | — |
| Cummerbunds | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Curated Brands: Plus Size | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Customers' Most-Loved: Sweaters Under $30 pASIN Test | Jewelry/accessories/other | 24 | 0 | 0 | 0 | — | — |
| Cycling | Clothing, Footwear | 48 | 7 | 2 | 2 | Black/Glowing Red (2021) (1); Black (1) | Nylon, Alloy Steel, Ethylene Vinyl Acetate, Suede, Rubber (1); Faux Leather, Nylon, Ethylene Vinyl Acetate (1) |
| Dance | Clothing, Footwear | 17 | 2 | 0 | 0 | — | — |
| Deal of the Day: Up to 40% Off Men's PUMA Sneakers | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Denim | Clothing | 54 | 15 | 0 | 0 | — | — |
| Denim Jackets | Clothing | 21 | 5 | 0 | 0 | — | — |
| Designer Shoes & Handbags | Jewelry/accessories/other | 5 | 0 | 0 | 0 | — | — |
| Diamond Jewelry starting $49 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Diamonds | Jewelry/accessories/other | 3 | 0 | 0 | 0 | — | — |
| Down & Down Alternative | Clothing | 87 | 15 | 0 | 0 | — | — |
| Down Jackets & Parkas | Clothing | 101 | 13 | 0 | 0 | — | — |
| Drawstring Bags | Jewelry/accessories/other | 19 | 6 | 0 | 0 | — | — |
| Dress | Clothing, Jewelry/accessories/other | 47 | 1 | 0 | 0 | — | — |
| Dress Coats | Clothing | 8 | 1 | 0 | 0 | — | — |
| Dress Shirts | Clothing | 93 | 13 | 0 | 0 | — | — |
| Dresses | Clothing, Jewelry/accessories/other | 656 | 136 | 1 | 1 | Black (1) | Steel (1) |
| Dresses & Jumpers | Clothing | 1 | 0 | 0 | 0 | — | — |
| Dresses Under $50 | Jewelry/accessories/other | 5 | 0 | 0 | 0 | — | — |
| Dresses- Checks | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Drop & Dangle | Jewelry/accessories/other | 503 | 213 | 0 | 0 | — | — |
| Earmuffs | Jewelry/accessories/other | 11 | 1 | 0 | 0 | — | — |
| Earring Jackets | Jewelry/accessories/other | 4 | 1 | 0 | 0 | — | — |
| Earrings | Jewelry/accessories/other | 113 | 32 | 0 | 0 | — | — |
| Editor's Picks: Women's New Arrivals | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Electric Shoe Polishers | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Engagement Rings | Jewelry/accessories/other | 22 | 10 | 0 | 0 | — | — |
| Equestrian Sport Boots | Footwear | 6 | 2 | 2 | 2 | Black (1); Brown (1) | Leather (2) |
| Equestrian Sports | Clothing | 1 | 0 | 0 | 0 | — | — |
| Eternity Rings | Jewelry/accessories/other | 16 | 8 | 0 | 0 | — | — |
| Evening Bags | Bags | 70 | 10 | 0 | 0 | — | — |
| Everyday Apparel Essentials | Jewelry/accessories/other | 20 | 0 | 0 | 0 | — | — |
| Everyday Bras | Clothing | 230 | 49 | 0 | 0 | — | — |
| Exotic Apparel | Clothing | 1 | 1 | 0 | 0 | — | — |
| Expert Beauty Trends | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Eyeglass Cases | Jewelry/accessories/other | 35 | 19 | 2 | 1 | Black (1); Wooden (1) | Acrylic MDF, PU Leather & Flannelette Fabric (1) |
| Eyeglass Chains | Jewelry/accessories/other | 21 | 9 | 0 | 0 | — | — |
| Eyewear | Jewelry/accessories/other | 4 | 2 | 0 | 0 | — | — |
| Eyewear Frames | Jewelry/accessories/other | 88 | 26 | 0 | 0 | — | — |
| Facial Hair | Jewelry/accessories/other | 2 | 1 | 0 | 0 | — | — |
| Fall-Ready Shirtdresses | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Family Athleisure | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Fascinators | Jewelry/accessories/other | 34 | 5 | 1 | 0 | Green02 (1) | — |
| Fashion | Jewelry/accessories/other | 7 | 0 | 0 | 0 | — | — |
| Fashion Backpacks | Bags | 34 | 9 | 1 | 0 | Bordeaux (1) | — |
| Fashion Gift Guide: For the Master of Make-Believe | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Fashion Hoodies & Sweatshirts | Clothing | 489 | 91 | 0 | 0 | — | — |
| Fashion Scarves | Jewelry/accessories/other | 136 | 41 | 0 | 0 | — | — |
| Fashion Sneakers | Footwear | 1017 | 97 | 0 | 0 | — | — |
| Fashion Watches | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Fashion-forward finds | Jewelry/accessories/other | 11 | 1 | 0 | 0 | — | — |
| Faux Body Piercing Jewelry | Jewelry/accessories/other | 10 | 3 | 0 | 0 | — | — |
| Feather Boas | Jewelry/accessories/other | 4 | 3 | 0 | 0 | — | — |
| Fedoras | Jewelry/accessories/other | 45 | 11 | 0 | 0 | — | — |
| Feminine Spring Blouses | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Field Hockey & Lacrosse | Footwear | 3 | 0 | 0 | 0 | — | — |
| Fine Jewelry for Women | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Fitness & Cross-Training | Footwear | 136 | 11 | 0 | 0 | — | — |
| Flat Front | Clothing | 47 | 10 | 0 | 0 | — | — |
| Flats | Footwear | 927 | 75 | 2 | 1 | Light Natural (1); Brown (1) | Polyester (1) |
| Fleece | Clothing | 111 | 25 | 0 | 0 | — | — |
| Flip-Flops | Footwear | 245 | 20 | 0 | 0 | — | — |
| Folding Umbrellas | Jewelry/accessories/other | 31 | 6 | 5 | 2 | Yellow (1); Flame red (1); Blue (1) | Nylon (1); Fabric and aluminium (1) |
| Food Service | Clothing | 2 | 1 | 0 | 0 | — | — |
| Food Service Shoes | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Football | Footwear | 11 | 1 | 0 | 0 | — | — |
| Footies | Clothing | 13 | 4 | 0 | 0 | — | — |
| Footwear | Jewelry/accessories/other | 13 | 5 | 0 | 0 | — | — |
| Formal | Clothing | 131 | 31 | 0 | 0 | — | — |
| Free One-Day Shipping on Jewelry, Watches, & More | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Full Slips | Clothing | 6 | 1 | 0 | 0 | — | — |
| Fun World Costumes | Jewelry/accessories/other | 2 | 1 | 0 | 0 | — | — |
| Fur & Faux Fur | Clothing | 42 | 2 | 0 | 0 | — | — |
| G-Strings & Thongs | Clothing | 24 | 9 | 0 | 0 | — | — |
| Garment Bags | Jewelry/accessories/other | 9 | 4 | 1 | 1 | Warm White (1) | Vinyl (1) |
| Garter Belts | Clothing | 1 | 0 | 0 | 0 | — | — |
| Gemstones | Jewelry/accessories/other | 5 | 2 | 0 | 0 | — | — |
| Girls | Clothing, Jewelry/accessories/other | 66 | 14 | 3 | 2 | Yellow (1); Gold (1); Grey/Pink (1) | not-applicable (1); Leather (1) |
| Girls Apparel | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Girls Athletic & Oxfords | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Girls Boots, Clogs & Mules | Jewelry/accessories/other | 4 | 0 | 0 | 0 | — | — |
| Girls Flats & Loafers | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Girls Leggings | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Girls Pants | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Girls Sandals & Pumps | Jewelry/accessories/other | 4 | 0 | 0 | 0 | — | — |
| Girls Sneakers | Jewelry/accessories/other | 19 | 0 | 0 | 0 | — | — |
| Girls Sneakers (fs, no puma) | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Girls Sneakers (no fs) | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Girls Swimwear 2 | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Girls' School Essentials | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Girls' Sneakers under $35 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Girls' Swimwear | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Gloves | Clothing, Jewelry/accessories/other | 105 | 27 | 15 | 12 | Black (6); Windproof-black (1); Blue,Red,White (1) | Nylon (2); Polyester (1); nylon (1) |
| Gloves & Mittens | Clothing, Jewelry/accessories/other | 14 | 4 | 0 | 0 | — | — |
| Golf | Clothing, Footwear | 67 | 4 | 0 | 0 | — | — |
| Graduation Cohort 1 - Daily | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Graduation Cohort 4 - Daily | Jewelry/accessories/other | 19 | 0 | 0 | 0 | — | — |
| Green Lit 197 | Jewelry/accessories/other | 2 | 1 | 0 | 0 | — | — |
| Green Lit 241 | Jewelry/accessories/other | 3 | 0 | 0 | 0 | — | — |
| Green Lit 641 | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Green Monday | 30% Off for Men | Jewelry/accessories/other | 3 | 0 | 0 | 0 | — | — |
| Green Monday | 30% Off for Women | Jewelry/accessories/other | 3 | 0 | 0 | 0 | — | — |
| Gym Bags | Jewelry/accessories/other | 4 | 0 | 0 | 0 | — | — |
| Gym Totes | Jewelry/accessories/other | 8 | 1 | 0 | 0 | — | — |
| Gymnastics | Clothing | 1 | 0 | 0 | 0 | — | — |
| HG Frequent Plus 4+ Stars | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Half Slips | Clothing | 22 | 10 | 0 | 0 | — | — |
| Handbag Accessories | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Handbag Hangers | Jewelry/accessories/other | 12 | 5 | 5 | 4 | Pink (1); Flower 17 (1); Gold (1) | Metal (2); Mother of pearl (1); Stainless Steel (1) |
| Handbag Organizers | Jewelry/accessories/other | 20 | 2 | 2 | 2 | Clear (1); French Tulips (1) | Plastic (1); Rayon (1) |
| Handbags & Wallets | Bags | 17 | 2 | 0 | 0 | — | — |
| Handbags Under $30 | Jewelry/accessories/other | 3 | 1 | 0 | 0 | — | — |
| Handkerchiefs | Jewelry/accessories/other | 10 | 2 | 0 | 0 | — | — |
| Hats | Clothing | 5 | 1 | 0 | 0 | — | — |
| Hats & Caps | Jewelry/accessories/other | 195 | 47 | 1 | 1 | Thin headbands for women (1) | Plastic (1) |
| Headbands | Jewelry/accessories/other | 55 | 22 | 9 | 7 | 1" Black Velvet (1); Multicolor (1); Heavyweight Space Dye Grey (1) | Leather (2); Plastic (1); Spandex (1) |
| Headwear | Jewelry/accessories/other | 58 | 26 | 2 | 2 | Multicoloured (1); Light Golden (1) | Horn (1); Rubber (1) |
| Health Care & Food Service | Footwear | 20 | 2 | 0 | 0 | — | — |
| Healthcare Uniforms | Jewelry/accessories/other | 6 | 0 | 0 | 0 | — | — |
| Heeled Sandals | Footwear | 325 | 54 | 0 | 0 | — | — |
| Henleys | Clothing | 55 | 12 | 1 | 1 | Boulder Heather (1) | Polyester,Cotton (1) |
| Hiking & Outdoor Recreation | Clothing | 1 | 1 | 1 | 1 | Multicoloured (1) | Polyester (1) |
| Hiking & Trekking | Footwear, Jewelry/accessories/other | 23 | 3 | 0 | 0 | — | — |
| Hiking Boots | Footwear | 135 | 14 | 1 | 1 | Obsidian (1) | Leather (1) |
| Hiking Shoes | Footwear | 116 | 7 | 1 | 1 | Tan/Gray/Black/Yellow (1) | Other (1) |
| Hipsters | Clothing | 27 | 4 | 0 | 0 | — | — |
| Hobo Bags | Bags | 36 | 7 | 0 | 0 | — | — |
| Holiday Together: Holiday Happy | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Hoodies | Clothing | 252 | 72 | 0 | 0 | — | — |
| Hoodies & Active | Clothing | 16 | 4 | 0 | 0 | — | — |
| Hoop | Jewelry/accessories/other | 200 | 81 | 0 | 0 | — | — |
| Hosiery | Clothing | 4 | 2 | 0 | 0 | — | — |
| Hunting | Footwear, Jewelry/accessories/other | 10 | 2 | 0 | 0 | — | — |
| ID Cases | Jewelry/accessories/other | 6 | 0 | 0 | 0 | — | — |
| Ice & Snow Grips | Jewelry/accessories/other | 8 | 4 | 3 | 4 | Black (2); 24-Teeth (1) | Thermoplastic Elastomer (TPE) (2); Linen (1); Silicone (1) |
| Ice Hockey | Clothing | 2 | 1 | 1 | 1 | Black (1) | Plastic (1) |
| Ice Skating | Clothing | 2 | 0 | 0 | 0 | — | — |
| Identification | Jewelry/accessories/other | 12 | 10 | 6 | 8 | Black (2); Yellow (1); Silver (1) | Stainless Steel (5); Not-applicable (1); Metal (1) |
| Industrial & Construction Boots | Footwear | 47 | 12 | 2 | 2 | Golden Grizzly (1); Black (1) | Leather (1); Plastic (1) |
| Insulated | Clothing | 23 | 2 | 0 | 0 | — | — |
| Insulated Shells | Clothing | 14 | 3 | 0 | 0 | — | — |
| Italian Style | Jewelry/accessories/other | 6 | 3 | 0 | 0 | — | — |
| Jackets | Clothing, Jewelry/accessories/other | 146 | 32 | 1 | 0 | Pink (01) (1) | — |
| Jackets & Coats | Clothing | 34 | 5 | 0 | 0 | — | — |
| Jackets and Coats | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Jammers | Clothing | 16 | 6 | 0 | 0 | — | — |
| Jeans | Clothing, Jewelry/accessories/other | 467 | 79 | 0 | 0 | — | — |
| Jerseys | Clothing | 106 | 29 | 3 | 2 | Green (1); Columbia Blue (1); White Blue Multi (1) | Polyester (1); 100-percent-polyester-jersey (1) |
| Jewelry | Jewelry/accessories/other | 62 | 18 | 0 | 1 | — | Gemstone (1) |
| Jewelry Accessories | Jewelry/accessories/other | 4 | 1 | 0 | 0 | — | — |
| Jewelry Armoires | Jewelry/accessories/other | 12 | 1 | 0 | 0 | — | — |
| Jewelry Boxes | Jewelry/accessories/other | 85 | 34 | 25 | 31 | Black (4); White (2); Blue (2) | Metal (5); Wood (3); Velvet (3) |
| Jewelry Boxes & Organizers | Jewelry/accessories/other | 12 | 4 | 4 | 4 | Black (3); Black/White/Red (1) | Metal (2); Faux Leather (1); Velvet (1) |
| Jewelry Rolls | Jewelry/accessories/other | 7 | 2 | 2 | 2 | Buddha (1); 2Navy Blue (1) | Polyester, Nylon (1); Leather (1) |
| Jewelry Sets | Jewelry/accessories/other | 111 | 41 | 0 | 0 | — | — |
| Jewelry Towers | Jewelry/accessories/other | 27 | 12 | 11 | 11 | Black (3); Clear (2); Combination Rotating Set (1) | Acrylic (3); Metal (1); Gold plated (1) |
| Jewelry Trays | Jewelry/accessories/other | 29 | 9 | 8 | 8 | Black (4); Beige (1); Clear (1) | Faux Leather, Wood (2); wooden, faux leather, cardboard base (1); Paper (1) |
| Jumpsuits | Clothing | 192 | 30 | 0 | 0 | — | — |
| Jumpsuits & Rompers | Clothing | 5 | 2 | 0 | 0 | — | — |
| Jumpsuits, Rompers & Overalls | Clothing | 9 | 0 | 0 | 0 | — | — |
| Keychains | Clothing | 80 | 42 | 34 | 34 | Silver (11); Black (2); Caregiver Keychain (1) | Stainless Steel (15); Metal (9); Acrylic (2) |
| Keyrings & Keychains | Jewelry/accessories/other | 20 | 10 | 9 | 9 | Silver, Black (1); Multi (1); Yellow (1) | Stainless Steel (4); Wood (1); Other (1) |
| Keyrings, Keychains & Charms | Jewelry/accessories/other | 108 | 49 | 40 | 35 | Silver (8); Multicolored (3); Multicoloured (2) | Stainless Steel (7); Metal (6); Acrylic (4) |
| Kids' Backpacks | Bags | 47 | 17 | 1 | 1 | Purple (1) | Nylon (1) |
| Kids' Luggage | Jewelry/accessories/other | 8 | 1 | 0 | 0 | — | — |
| Kids' Shoes Markdown | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Kids' and Baby Halloween Costumes | Jewelry/accessories/other | 8 | 0 | 0 | 0 | — | — |
| Knee-High | Footwear | 109 | 11 | 0 | 0 | — | — |
| Knee-High Socks | Clothing | 1 | 0 | 0 | 0 | — | — |
| Knits & Tees | Jewelry/accessories/other | 5 | 0 | 0 | 0 | — | — |
| Lab Coats | Clothing | 6 | 1 | 0 | 0 | — | — |
| Layette Sets | Clothing | 8 | 3 | 1 | 1 | Red (1) | Cotton (1) |
| Leather & Faux Leather | Clothing | 95 | 28 | 0 | 0 | — | — |
| Lee Lowest Prices Of The Season | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Leg Warmers | Clothing, Jewelry/accessories/other | 34 | 11 | 0 | 0 | — | — |
| Leg Warmers & Hosiery | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Leggings | Clothing | 383 | 67 | 2 | 2 | Maroon Capris (1); Navy (1) | Spandex (1); Spandex, Cotton (1) |
| Leotards | Clothing | 4 | 2 | 0 | 0 | — | — |
| Liners & Ankle Socks | Clothing | 17 | 10 | 0 | 1 | — | Alpaca (1) |
| Lingerie | Clothing | 3 | 2 | 0 | 0 | — | — |
| Lingerie Semi-Annual Savings | Jewelry/accessories/other | 3 | 0 | 0 | 0 | — | — |
| Lingerie Sets | Clothing | 22 | 6 | 0 | 0 | — | — |
| Lingerie, Sleep & Lounge | Clothing | 2 | 2 | 0 | 0 | — | — |
| Link | Jewelry/accessories/other | 126 | 54 | 42 | 46 | Silver (10); Black (5); silver (3) | Metal (20); Stainless Steel (7); Sterling Silver (3) |
| Loafers | Footwear | 28 | 0 | 0 | 0 | — | — |
| Loafers & Slip-Ons | Footwear | 665 | 68 | 0 | 0 | — | — |
| Lockets | Jewelry/accessories/other | 22 | 8 | 0 | 0 | — | — |
| Loose Gemstones | Jewelry/accessories/other | 28 | 14 | 3 | 2 | 14mm/Black (1); Midnight Aquamarine Blue (1); Smooth Round (1) | Plastic (1); Gemstone (1) |
| Luggage | Jewelry/accessories/other | 42 | 6 | 0 | 0 | — | — |
| Luggage & Travel Gear | Jewelry/accessories/other | 23 | 4 | 1 | 0 | Orange/Yellow (1) | — |
| Luggage Handle Wraps | Jewelry/accessories/other | 1 | 1 | 1 | 1 | Personalized. (1) | Polyester (1) |
| Luggage Locks | Jewelry/accessories/other | 7 | 2 | 1 | 2 | black (1) | Alloy Steel (1); Plastic (1) |
| Luggage Scales | Jewelry/accessories/other | 7 | 2 | 2 | 2 | SILVER (1); Silver (1) | Stainless Steel,Lead (1); Plastic (1) |
| Luggage Sets | Jewelry/accessories/other | 27 | 6 | 0 | 0 | — | — |
| Luggage Straps | Jewelry/accessories/other | 15 | 7 | 4 | 5 | 2PCS (1); Orange (1); Black, Silver (1) | Plastic (1); Leather (1); Plastic, Metal (1) |
| Luggage Tags | Jewelry/accessories/other | 39 | 22 | 16 | 18 | White (2); Multicolored (2); Clear (1) | Silicone (4); Leather (3); Plastic (2) |
| Luggage Tags & Handle Wraps | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| MFN ONLY V2 | Jewelry/accessories/other | 18 | 2 | 0 | 0 | — | — |
| MFN Only | Jewelry/accessories/other | 4 | 0 | 0 | 0 | — | — |
| Made in USA | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Markdowns | Jewelry/accessories/other | 4 | 0 | 0 | 0 | — | — |
| Mary Jane | Footwear | 12 | 3 | 0 | 0 | — | — |
| Masks | Jewelry/accessories/other | 105 | 28 | 2 | 3 | Caucasian Skin Tone (1); Blue (1) | Polyester (3) |
| Medical | Clothing | 4 | 0 | 0 | 0 | — | — |
| Memorial Day Savings 2016 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Men | Clothing, Jewelry/accessories/other | 185 | 36 | 1 | 2 | Brown (1) | Leather (1); Stainless Steel (1) |
| Men's Action Sport Watches | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Men's Activewear: Bottoms | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Men's Denim Updates | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Men's Halloween Costumes | Jewelry/accessories/other | 6 | 1 | 0 | 0 | — | — |
| Men's Off-to-College Essentials | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Men's Outerwear: Parka | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Men's Shorts Under $25 - Prod | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Men's Slippers Under $40 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Men's Swimwear | Jewelry/accessories/other | 3 | 0 | 0 | 0 | — | — |
| Men's Watches Under $50 | Jewelry/accessories/other | 5 | 0 | 0 | 0 | — | — |
| Messenger Bags | Jewelry/accessories/other | 58 | 6 | 0 | 0 | — | — |
| Mid-Calf | Footwear | 137 | 12 | 0 | 0 | — | — |
| Military | Clothing | 9 | 5 | 1 | 0 | Multicolored (1) | — |
| Military & Tactical | Footwear | 8 | 2 | 0 | 0 | — | — |
| Minimizers | Clothing | 10 | 1 | 0 | 0 | — | — |
| Mittens | Jewelry/accessories/other | 17 | 5 | 2 | 2 | Grey (1); Black (1) | Fleece,Leather (1); Polyester, Faux Leather (1) |
| Money Clips | Jewelry/accessories/other | 14 | 7 | 3 | 3 | Black (1); Gold (1); Navy Blue (1) | Leather (1); Brass (1); Carbon Fiber (1) |
| Most Gifted Styles | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Motorcycle | Jewelry/accessories/other | 73 | 1 | 0 | 0 | — | — |
| Motorcycle & Combat | Footwear | 12 | 0 | 0 | 0 | — | — |
| Mules & Clogs | Footwear | 283 | 31 | 0 | 0 | — | — |
| Must See Deals | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Neck Gaiters | Jewelry/accessories/other | 41 | 8 | 0 | 0 | — | — |
| Necklaces | Jewelry/accessories/other | 329 | 131 | 4 | 4 | Silver (2); Yellow (1); Silver,Bronze (1) | Metal (2); Stainless Steel (1); Yellow Gold (1) |
| Necklaces & Pendants | Jewelry/accessories/other | 6 | 1 | 0 | 0 | — | — |
| Neckties | Clothing, Jewelry/accessories/other | 66 | 24 | 1 | 1 | Black (1) | Nylon (1) |
| New Looks from Prime Wardrobe | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Newsboy Caps | Jewelry/accessories/other | 34 | 13 | 0 | 0 | — | — |
| Night Out | Clothing | 17 | 2 | 0 | 0 | — | — |
| Nightgowns | Clothing, Jewelry/accessories/other | 22 | 3 | 0 | 0 | — | — |
| Nightgowns & Sleepshirts | Clothing, Jewelry/accessories/other | 178 | 30 | 0 | 0 | — | — |
| Nightshirts | Clothing | 1 | 0 | 0 | 0 | — | — |
| No Show & Liner Socks | Clothing | 33 | 9 | 0 | 0 | — | — |
| Not-Your-Mother's Cableknit | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Novelty | Clothing | 195 | 26 | 3 | 2 | Black With Silver (1); PINK CHEETAH (1); White (1) | synthetic leather, faux leather (1); Plastic (1) |
| Novelty & More | Jewelry/accessories/other | 13 | 7 | 1 | 2 | Black (1) | Leather (1); Silicone (1) |
| Nursing & Maternity Bras | Jewelry/accessories/other | 3 | 2 | 0 | 0 | — | — |
| Off to College Fashion | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Old Glory Exclusives | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| On Sale Now | Jewelry/accessories/other | 7 | 0 | 0 | 0 | — | — |
| One Pieces | Clothing | 20 | 3 | 1 | 0 | Turtle Green (1) | — |
| One-Piece Pajamas | Clothing | 29 | 6 | 0 | 0 | — | — |
| One-Piece Suits | Clothing | 47 | 8 | 2 | 2 | Daze (1); Pink (1) | Polyester (2) |
| One-Pieces | Clothing | 259 | 45 | 0 | 0 | — | — |
| Outerwear | Clothing | 34 | 13 | 0 | 0 | — | — |
| Outlet: Clothing | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Over $50 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Over-the-Knee | Footwear | 16 | 1 | 0 | 0 | — | — |
| Overalls | Clothing | 50 | 16 | 0 | 0 | — | — |
| Overalls & Coveralls | Clothing | 13 | 4 | 0 | 0 | — | — |
| Oxford & Derby | Footwear | 6 | 2 | 0 | 0 | — | — |
| Oxford & Loafer | Footwear | 3 | 0 | 0 | 0 | — | — |
| Oxfords | Footwear | 283 | 22 | 0 | 0 | — | — |
| Oxfords & Loafers | Footwear | 3 | 0 | 0 | 0 | — | — |
| PD23_All fashion deals running on all of lead up v5 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| PP Boots Under $75 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| PP Slippers Under $40 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Packing Organizers | Jewelry/accessories/other | 57 | 11 | 9 | 9 | Black (3); Bluish Grey (1); Beige (1) | Nylon (5); Polyester (2); Nylon 600D (1) |
| Paddle Fans | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Pads & Enhancers | Clothing | 9 | 6 | 1 | 0 | Beige (1) | — |
| Pajama Bottoms | Clothing | 4 | 2 | 0 | 0 | — | — |
| Pajama Sets | Clothing | 128 | 21 | 0 | 1 | — | Cotton (1) |
| Pajamas, Loungewear & More | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Pant Sets | Clothing | 203 | 36 | 0 | 0 | — | — |
| Panties | Clothing, Jewelry/accessories/other | 29 | 6 | 0 | 0 | — | — |
| Pants | Clothing | 297 | 79 | 3 | 2 | Black (2); B05-purple (1) | 90% Polyester/ 10% Spandex (1); Spandex, Nylon (1) |
| Pants & Capris | Clothing | 24 | 5 | 0 | 0 | — | — |
| Passport Covers | Jewelry/accessories/other | 13 | 6 | 6 | 6 | Black (2); Clear (1); Red (1) | Faux Leather (2); Plastic (1); Polyester (1) |
| Passport Wallets | Jewelry/accessories/other | 7 | 2 | 2 | 2 | Dark Brown (1); Black (1) | Leather (1); Polyester (1) |
| PattyBoutik Apparel | Jewelry/accessories/other | 16 | 0 | 0 | 0 | — | — |
| Pearl Strands | Jewelry/accessories/other | 18 | 2 | 0 | 0 | — | — |
| Pendant Enhancers | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Pendant Necklaces | Jewelry/accessories/other | 531 | 210 | 2 | 1 | Gold-tone Pink (1); Silver (1) | Rhinestone (1) |
| Pendants | Jewelry/accessories/other | 60 | 23 | 1 | 2 | Stainless Steel (1) | Stainless Steel (1); Metal (1) |
| Pendants & Coins | Jewelry/accessories/other | 28 | 13 | 0 | 0 | — | — |
| Pendants Only | Jewelry/accessories/other | 83 | 42 | 3 | 3 | Silver (2); White CZ (1) | Metal (1); Sterling Silver (1); Stainless Steel (1) |
| Piercing Jewelry | Jewelry/accessories/other | 18 | 5 | 0 | 0 | — | — |
| Plain Silver Jewelry | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Platforms & Wedges | Footwear | 545 | 42 | 0 | 0 | — | — |
| Playwear | Clothing | 37 | 7 | 0 | 0 | — | — |
| Pleated | Clothing | 2 | 0 | 0 | 0 | — | — |
| Plugs | Jewelry/accessories/other | 40 | 21 | 0 | 0 | — | — |
| Plus-Size Fashion | Jewelry/accessories/other | 29 | 0 | 0 | 0 | — | — |
| Pocket Squares | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Pocket Watch Chains | Jewelry/accessories/other | 5 | 3 | 0 | 0 | — | — |
| Pocket Watches | Jewelry/accessories/other | 13 | 5 | 0 | 0 | — | — |
| Polos | Clothing, Jewelry/accessories/other | 219 | 46 | 3 | 2 | Black/White (1); Brilliance (819)/Metallic Silver (1); Navy White Tipping (1) | Cotton (2) |
| Premium Fashion Testing | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Premium Tops | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Pretty Winter Floral Prints | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Prime Day: 30% off Select Clothing, Shoes & More for Men, Women, Kids & Baby | Jewelry/accessories/other | 5 | 0 | 0 | 0 | — | — |
| Prime Day: 30% off select fashion | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Prime Wardrobe: Columbia Try Before You Buy | Jewelry/accessories/other | 3 | 0 | 0 | 0 | — | — |
| Prime Wardrobe: Levi's Try Before You Buy | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Prime Wardrobe: New Arrivals | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Prime Wardrobe: Under Armour | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Prom- Dresses | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Promise Rings | Jewelry/accessories/other | 6 | 3 | 0 | 0 | — | — |
| Pullover | Clothing | 8 | 1 | 0 | 0 | — | — |
| Pullovers | Clothing | 379 | 58 | 1 | 1 | Pearl Heather Grey (1) | Cotton Blend (1) |
| Pumps | Footwear | 630 | 48 | 0 | 0 | — | — |
| Quilted Lightweight Jackets | Clothing | 15 | 4 | 0 | 0 | — | — |
| Racquet Sports | Footwear | 6 | 0 | 0 | 0 | — | — |
| Rain | Footwear, Jewelry/accessories/other | 111 | 17 | 0 | 1 | — | Rubber (1) |
| Rain Boots | Footwear | 1 | 0 | 0 | 0 | — | — |
| Rain Footwear | Footwear | 15 | 3 | 1 | 0 | Black (1) | — |
| Rain Hats | Jewelry/accessories/other | 4 | 1 | 0 | 0 | — | — |
| Rain Jackets | Clothing | 15 | 2 | 0 | 0 | — | — |
| Raincoats | Clothing | 49 | 9 | 0 | 0 | — | — |
| Rash Guard Sets | Clothing | 18 | 6 | 0 | 0 | — | — |
| Rash Guard Shirts | Clothing | 81 | 17 | 1 | 0 | Chrome (1) | — |
| Repair Tools & Kits | Jewelry/accessories/other | 23 | 10 | 1 | 3 | 2pcs,s+l (1) | Stainless Steel (1); Chromium Vanadium Steel (1); Silicone, Leather (1) |
| Replacement Sunglass Lenses | Jewelry/accessories/other | 61 | 47 | 3 | 0 | Dark Black (1); Blue - Polarized (1); Stealth Black & Metallic Silver & Fire Red (1) | — |
| Retainers | Jewelry/accessories/other | 6 | 2 | 0 | 0 | — | — |
| Rhinestones earrings | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Riding | Jewelry/accessories/other | 162 | 13 | 0 | 0 | — | — |
| Ring Enhancers | Jewelry/accessories/other | 3 | 2 | 0 | 0 | — | — |
| Ring Sizers | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Rings | Jewelry/accessories/other | 373 | 127 | 1 | 1 | Silver (1) | Alloy,Metal (1) |
| Road Running | Footwear | 522 | 32 | 1 | 0 | Elemental Rose/Particle Rose/Gunsmoke (1) | — |
| Robes | Clothing | 195 | 26 | 0 | 0 | — | — |
| Robes, Capes & Jackets | Jewelry/accessories/other | 26 | 14 | 0 | 0 | — | — |
| Rompers | Clothing | 116 | 19 | 0 | 0 | — | — |
| Rugby | Footwear | 1 | 0 | 0 | 0 | — | — |
| Running | Clothing, Footwear | 238 | 16 | 0 | 0 | — | — |
| Sandals | Footwear | 586 | 49 | 1 | 0 | Gold (1) | — |
| Satchels | Bags | 61 | 11 | 0 | 0 | — | — |
| Save up to X% on Burt's Bees | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Scarves | Clothing, Jewelry/accessories/other | 8 | 4 | 0 | 0 | — | — |
| Scarves & Wraps | Jewelry/accessories/other | 6 | 3 | 0 | 0 | — | — |
| School Uniforms | Clothing | 1 | 0 | 0 | 0 | — | — |
| Screws | Jewelry/accessories/other | 14 | 8 | 0 | 0 | — | — |
| Scrub Bottoms | Clothing | 31 | 7 | 0 | 0 | — | — |
| Scrub Jackets | Clothing | 14 | 1 | 0 | 0 | — | — |
| Scrub Sets | Clothing | 22 | 2 | 0 | 0 | — | — |
| Scrub Tops | Clothing | 58 | 12 | 0 | 0 | — | — |
| Sets | Clothing, Jewelry/accessories/other | 610 | 91 | 0 | 0 | — | — |
| Shapewear | Clothing | 4 | 0 | 0 | 0 | — | — |
| Shearling | Jewelry/accessories/other | 46 | 0 | 0 | 0 | — | — |
| Sheers | Clothing | 30 | 7 | 0 | 0 | — | — |
| Shells | Clothing | 34 | 9 | 0 | 0 | — | — |
| Shirt Studs | Jewelry/accessories/other | 5 | 4 | 0 | 0 | — | — |
| Shirts | Clothing, Jewelry/accessories/other | 86 | 16 | 1 | 1 | White/Collegiate Navy (1) | Blend (1) |
| Shirts Under $30 | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Shoe & Boot Trees | Jewelry/accessories/other | 17 | 5 | 1 | 3 | Black (1) | Plastic (1); USA GROWN Eastern Red Cedar (1); Wood (1) |
| Shoe Bags | Jewelry/accessories/other | 6 | 1 | 0 | 0 | — | — |
| Shoe Brushes | Jewelry/accessories/other | 6 | 3 | 3 | 2 | White (1); Black (1); 191-000 (1) | Ethylene Vinyl Acetate (EVA) (1); Rubber (1) |
| Shoe Care & Accessories | Jewelry/accessories/other | 7 | 2 | 1 | 1 | _ (1) | Plastic (1) |
| Shoe Care Kits | Jewelry/accessories/other | 3 | 1 | 1 | 1 | Heel Soles (1) | Leather, Rubber (1) |
| Shoe Decoration Charms | Jewelry/accessories/other | 44 | 19 | 1 | 1 | Black (1) | Faux Leather (1) |
| Shoe Dryers | Jewelry/accessories/other | 5 | 3 | 3 | 3 | Black (1); Original (1); Easy Knob (1) | Leather (2); Plastic (1) |
| Shoe Horns & Boot Jacks | Jewelry/accessories/other | 8 | 4 | 0 | 0 | — | — |
| Shoe Measuring Devices | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Shoe Polishes | Jewelry/accessories/other | 5 | 2 | 0 | 0 | — | — |
| Shoe Treatments & Polishes | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Shoe, Jewelry & Watch Accessories | Jewelry/accessories/other | 1 | 1 | 0 | 1 | — | Wood (1) |
| Shoelaces | Jewelry/accessories/other | 66 | 20 | 3 | 2 | Multi (2); Brown (1) | Blend (2) |
| Shoes | Footwear | 1299 | 46 | 2 | 1 | White (1); Black (1) | Thermoplastic Polyurethane (1) |
| Shop Your Style: Classic | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Shop by Designer | Jewelry/accessories/other | 3 | 1 | 0 | 0 | — | — |
| Shop by Occasion for Her: Vacation | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Shopbop September 2019 EOTS | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Short Sets | Clothing | 84 | 27 | 0 | 0 | — | — |
| Shorts | Clothing | 137 | 32 | 0 | 0 | — | — |
| Shorts & Trunks | Clothing | 1 | 0 | 0 | 0 | — | — |
| Shoulder Bags | Bags, Jewelry/accessories/other | 257 | 35 | 2 | 1 | Texas-flag (1); Black (1) | Leather (1) |
| Shrugs | Clothing | 22 | 5 | 0 | 0 | — | — |
| Skateboarding | Footwear | 83 | 4 | 0 | 0 | — | — |
| Ski Suits | Clothing | 1 | 1 | 0 | 0 | — | — |
| Skiing | Clothing | 7 | 2 | 1 | 1 | Black, Natural, Grey, White (1) | other (1) |
| Skirt Sets | Clothing | 25 | 4 | 0 | 0 | — | — |
| Skirts | Clothing | 202 | 48 | 1 | 1 | Black (1) | Polyester (1) |
| Skirts & Skorts | Clothing | 1 | 0 | 0 | 0 | — | — |
| Skirts, Scooters & Skorts | Clothing | 1 | 0 | 0 | 0 | — | — |
| Skirts, Skooters & Skorts | Clothing | 5 | 2 | 0 | 1 | — | Polyester (1) |
| Skorts | Clothing | 1 | 0 | 0 | 0 | — | — |
| Skullies & Beanies | Jewelry/accessories/other | 156 | 45 | 0 | 0 | — | — |
| Sleep & Lounge | Clothing | 3 | 1 | 1 | 1 | Blue (1) | Satin (1) |
| Sleep Bottoms | Clothing | 68 | 16 | 0 | 0 | — | — |
| Sleep Sets | Clothing | 37 | 9 | 0 | 0 | — | — |
| Sleep Tops | Clothing | 4 | 1 | 0 | 0 | — | — |
| Slides | Footwear | 190 | 33 | 2 | 2 | Active Red (1); White/Navy/Red (1) | Nylon (1); Rubber (1) |
| Slipper Socks | Clothing | 46 | 11 | 0 | 0 | — | — |
| Slippers | Footwear | 538 | 77 | 1 | 1 | Brown (1) | Faux Fur (1) |
| Slips | Clothing | 3 | 3 | 0 | 0 | — | — |
| Smartwatches | Jewelry/accessories/other | 6 | 2 | 2 | 0 | Smoke (1); Smoke Grey (1) | — |
| Snake | Jewelry/accessories/other | 10 | 3 | 3 | 1 | Russian Gold (1); Shiny Gold (1); Silver (1) | Metal (1) |
| Sneakers | Footwear | 341 | 25 | 0 | 0 | — | — |
| Snow & Cold Weather | Jewelry/accessories/other | 232 | 16 | 0 | 0 | — | — |
| Snow & Rainwear | Clothing | 2 | 1 | 0 | 0 | — | — |
| Snow Boots | Footwear | 4 | 0 | 0 | 0 | — | — |
| Snow Pants & Bibs | Clothing | 6 | 0 | 0 | 0 | — | — |
| Snow Suits | Clothing | 16 | 3 | 0 | 0 | — | — |
| Snowboarding | Clothing | 2 | 0 | 0 | 0 | — | — |
| Soccer | Footwear | 88 | 12 | 0 | 0 | — | — |
| Soccer & Futsal | Clothing | 2 | 0 | 0 | 0 | — | — |
| Socks | Clothing, Jewelry/accessories/other | 376 | 121 | 5 | 5 | 3 Pairs Black (1); Toewa02 (1); Purple Red Green (3 Pairs) (1) | Spandex, Polycotton (1); Polyester, Spandex (1); Wool (1) |
| Socks & Hosiery | Clothing | 1 | 1 | 0 | 0 | — | — |
| Softball & Baseball | Footwear | 4 | 1 | 0 | 0 | — | — |
| Softshell Jackets | Clothing | 1 | 0 | 0 | 0 | — | — |
| Special Occasion | Clothing | 140 | 40 | 0 | 0 | — | — |
| Special Occasion Accessories | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Special Occasion Gloves | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Splurgeworthy Womens Shoes | Jewelry/accessories/other | 2 | 1 | 0 | 0 | — | — |
| Sport Coats & Blazers | Clothing | 43 | 10 | 1 | 1 | Gray Silver (1) | Metal (1) |
| Sport Headbands | Jewelry/accessories/other | 14 | 5 | 4 | 3 | Black(N0003527-075)/G (1); Tropical Tide (425)/Metallic Silver (1); ORCHID (1) | Polyester (1); polyester (1); Dryline (1) |
| Sport Sandals | Footwear | 15 | 0 | 0 | 0 | — | — |
| Sport Sandals & Slides | Footwear | 132 | 14 | 0 | 0 | — | — |
| Sport Specific Clothing | Clothing | 7 | 3 | 0 | 0 | — | — |
| Sport Watches | Jewelry/accessories/other | 8 | 1 | 0 | 0 | — | — |
| Sports Bras | Clothing | 166 | 20 | 0 | 0 | — | — |
| Sports Duffels | Jewelry/accessories/other | 29 | 6 | 0 | 0 | — | — |
| Stacking | Jewelry/accessories/other | 37 | 17 | 0 | 0 | — | — |
| Statement | Jewelry/accessories/other | 249 | 83 | 0 | 0 | — | — |
| Stick Umbrellas | Jewelry/accessories/other | 31 | 8 | 7 | 2 | Rainbow (2); Black/Titanium Silver (1); Coca Cola Cans Red (1) | Fiberglass, Iron (1); Metal (1) |
| Strand | Jewelry/accessories/other | 46 | 17 | 15 | 14 | Black (2); Silver (1); White (1) | Glass (2); Rhinestone (1); Nylon (1) |
| Strands | Jewelry/accessories/other | 29 | 13 | 0 | 0 | — | — |
| Straps | Clothing | 2 | 1 | 0 | 0 | — | — |
| Street, Surf & Skate | Jewelry/accessories/other | 3 | 1 | 0 | 0 | — | — |
| Stretch | Jewelry/accessories/other | 75 | 32 | 30 | 26 | Pink (3); White (2); Purple (2) | Stone (4); Crystal (3); Gemstone (2) |
| Stud | Jewelry/accessories/other | 358 | 145 | 0 | 1 | — | Sterling Silver (1) |
| Students' Top Rated | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Studs | Jewelry/accessories/other | 25 | 9 | 0 | 0 | — | — |
| Suit Jackets | Clothing | 6 | 1 | 0 | 0 | — | — |
| Suit Pants | Clothing | 3 | 0 | 0 | 0 | — | — |
| Suit Sets | Clothing | 34 | 6 | 0 | 0 | — | — |
| Suitcases | Jewelry/accessories/other | 50 | 6 | 1 | 1 | Black (1) | 600D Polyester (1) |
| Suits | Clothing | 41 | 9 | 0 | 0 | — | — |
| Sun Hats | Clothing, Jewelry/accessories/other | 66 | 17 | 0 | 0 | — | — |
| Sunglasses | Jewelry/accessories/other | 540 | 124 | 4 | 2 | Blue Mirror (1); Clear,red (1); Black (1) | Polycarbonate (2) |
| Sunglasses & Eyewear | Clothing | 4 | 1 | 0 | 0 | — | — |
| Sunglasses & Eyewear Accessories | Jewelry/accessories/other | 2 | 1 | 0 | 0 | — | — |
| Sunglasses Starting at $15 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Sunsuits | Clothing | 5 | 3 | 0 | 0 | — | — |
| Suspenders | Jewelry/accessories/other | 29 | 15 | 0 | 0 | — | — |
| Sweaters | Clothing | 50 | 13 | 0 | 0 | — | — |
| Sweatpants | Clothing | 127 | 24 | 0 | 0 | — | — |
| Sweatshirts | Clothing | 47 | 17 | 0 | 0 | — | — |
| Swim | Clothing | 4 | 0 | 0 | 0 | — | — |
| Swim Diapers | Clothing | 6 | 0 | 0 | 0 | — | — |
| Swim Pants | Clothing | 1 | 0 | 0 | 0 | — | — |
| Swimsuits & Cover Ups | Clothing | 13 | 2 | 0 | 0 | — | — |
| Swimwear | Clothing | 25 | 2 | 0 | 0 | — | — |
| T-Shirts | Clothing, Jewelry/accessories/other | 2807 | 1037 | 35 | 21 | Black (18); Hot Pink (1); Navy (1) | Polyester, Cotton (9); Cotton (6); Jersey (2) |
| Tactical boots | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Take 25% Off | Holiday Savings for Women | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Tank Tops | Clothing | 87 | 25 | 0 | 0 | — | — |
| Tankini Sets | Clothing | 4 | 3 | 0 | 0 | — | — |
| Tankinis | Clothing | 6 | 1 | 0 | 0 | — | — |
| Tanks & Camis | Clothing, Jewelry/accessories/other | 499 | 101 | 0 | 0 | — | — |
| Tanks Tops | Clothing | 43 | 19 | 2 | 1 | Black (1); Red (1) | Cotton (1) |
| Tapers | Jewelry/accessories/other | 11 | 7 | 0 | 0 | — | — |
| Teddies & Bodysuits | Clothing | 4 | 1 | 0 | 0 | — | — |
| Tees | Clothing, Jewelry/accessories/other | 202 | 65 | 0 | 0 | — | — |
| Tees & Tops for College under $25 | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Tennis | Jewelry/accessories/other | 15 | 7 | 6 | 6 | Peridot (1); Simulated Emerald (1); White,White Gold (1) | Gemstone (1); Sterling Silver , Gemstone (1); Gemstone, Diamond (1) |
| Tennis & Racquet Sports | Footwear | 74 | 4 | 0 | 0 | — | — |
| Test Color | Jewelry/accessories/other | 5 | 2 | 0 | 0 | — | — |
| The Women's Warm-Weather Edit | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Thermal Underwear | Clothing | 2 | 0 | 0 | 0 | — | — |
| Tie Clips | Jewelry/accessories/other | 15 | 6 | 1 | 1 | Multicoloured (1) | Brass (1) |
| Tie Pins | Jewelry/accessories/other | 8 | 4 | 1 | 1 | Multi Color (1) | Metal (1) |
| Tie Sets | Jewelry/accessories/other | 30 | 7 | 0 | 0 | — | — |
| Ties, Cummerbunds & Pocket Squares | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Tights | Clothing, Jewelry/accessories/other | 57 | 14 | 0 | 0 | — | — |
| Tights & Hosiery | Jewelry/accessories/other | 3 | 0 | 0 | 0 | — | — |
| Tights & Pants | Clothing | 17 | 2 | 0 | 0 | — | — |
| Tights, Pants & Shorts | Clothing | 1 | 0 | 0 | 0 | — | — |
| Toddler Size 6 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Toddler Size 7 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Toddler Size 8 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Toe Rings | Jewelry/accessories/other | 19 | 8 | 0 | 0 | — | — |
| Top 1,000 3P ASINs Under $15 | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Top 50 by Product Type | Jewelry/accessories/other | 32 | 1 | 0 | 0 | — | — |
| Top Brands Under $149 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Top Gifts for the Family: Colorful Crocs | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Top Rated Fashion Capital Favorites | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Top-Handle Bags | Bags | 101 | 4 | 0 | 0 | — | — |
| Tops | Clothing, Jewelry/accessories/other | 195 | 59 | 2 | 1 | Pink (1); Blue (1) | Cotton (1) |
| Tops & Corsets | Jewelry/accessories/other | 3 | 2 | 0 | 0 | — | — |
| Tops & Tees | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Tops, Tees & Blouses | Clothing | 104 | 13 | 0 | 0 | — | — |
| Total Sleepwear & Robes | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Total Sweaters | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Totes | Bags, Jewelry/accessories/other | 188 | 38 | 1 | 1 | Black (1) | Polyester (1) |
| Track & Active Jackets | Clothing | 53 | 9 | 0 | 0 | — | — |
| Track & Field & Cross Country | Footwear | 14 | 0 | 0 | 0 | — | — |
| Track Pants | Clothing | 37 | 9 | 0 | 0 | — | — |
| Tracksuits | Clothing | 84 | 17 | 0 | 0 | — | — |
| Trail Running | Footwear | 139 | 4 | 0 | 0 | — | — |
| Training Bras | Clothing | 10 | 1 | 0 | 0 | — | — |
| Travel Accessories | Jewelry/accessories/other | 7 | 2 | 1 | 1 | 2.2 Hook & Loop: Leopard (1) | Oxford cloth (1) |
| Travel Duffels | Jewelry/accessories/other | 78 | 20 | 1 | 0 | Pink/Black/White (1) | — |
| Travel Totes | Jewelry/accessories/other | 20 | 8 | 0 | 0 | — | — |
| Travel Wallets | Jewelry/accessories/other | 13 | 4 | 1 | 1 | Beige (1) | Nylon (1) |
| Trench & Rain | Clothing | 24 | 8 | 0 | 0 | — | — |
| Trench Coats | Clothing | 25 | 3 | 0 | 0 | — | — |
| Trunks | Clothing | 72 | 16 | 0 | 0 | — | — |
| Tunics | Clothing, Jewelry/accessories/other | 521 | 62 | 1 | 1 | Navy (1) | Polyester,Spandex (1) |
| Tunnels | Jewelry/accessories/other | 37 | 15 | 0 | 0 | — | — |
| TurboTax Refund Bonus Exclusive: 20% Off Select Shoes | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Tuxedo Shirts | Clothing | 2 | 1 | 0 | 0 | — | — |
| Tuxedos | Clothing | 7 | 3 | 0 | 0 | — | — |
| Two-Piece Suits | Clothing | 6 | 0 | 0 | 0 | — | — |
| Two-Pieces | Clothing | 2 | 0 | 0 | 0 | — | — |
| Ugly Holiday Sweaters (and More) for the Family | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Umbrellas | Jewelry/accessories/other | 11 | 2 | 2 | 0 | White (1); Multicoloured (1) | — |
| Under $30 | Jewelry/accessories/other | 8 | 0 | 0 | 0 | — | — |
| Under $50 | Jewelry/accessories/other | 7 | 0 | 0 | 0 | — | — |
| Undershirts | Clothing | 46 | 17 | 0 | 0 | — | — |
| Undershirts, Tanks & Camisoles | Clothing | 2 | 2 | 0 | 0 | — | — |
| Undershorts | Clothing | 1 | 1 | 1 | 1 | Black Tread (1) | Polyester, Spandex (1) |
| Underwear | Clothing | 12 | 4 | 0 | 0 | — | — |
| Uniform Dress Shoes | Footwear | 1 | 0 | 0 | 0 | — | — |
| Up to 20% Off Select Jewelry & Watches | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Up to 30% off Shoes, Handbags and More | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Up to 30% off select shoes from Clarks, ECCO, and more | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Up to 70% Off Men's Mid-Summer Savings | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Varsity Jackets | Clothing | 8 | 3 | 0 | 0 | — | — |
| Vests | Clothing | 153 | 37 | 1 | 1 | Beige (1) | Polyester (1) |
| Veterans Day Savings: 20% or More Off | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Visors | Clothing, Jewelry/accessories/other | 10 | 3 | 0 | 0 | — | — |
| Volleyball | Footwear | 8 | 1 | 1 | 1 | Black (1) | Rubber (1) |
| Waist Cinchers | Clothing | 17 | 3 | 3 | 3 | Black (2); A-black-4 Meters (1) | Spandex, Rubber, Cotton (1); Cotton (1); Rubber+Polyester (1) |
| Waist Packs | Jewelry/accessories/other | 26 | 8 | 0 | 1 | — | Polyester, Spandex (1) |
| Walking | Footwear | 342 | 33 | 0 | 0 | — | — |
| Walking Sticks & Canes | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Wallets | Clothing, Jewelry/accessories/other | 370 | 91 | 73 | 71 | Black (15); Brown (5); Dark Brown (3) | Leather (44); Faux Leather (9); Polyester (3) |
| Wallets, Card Cases & Money Organizers | Jewelry/accessories/other | 10 | 1 | 1 | 1 | Black (1) | Leather (1) |
| Wands | Jewelry/accessories/other | 1 | 1 | 0 | 0 | — | — |
| Watch Bands | Jewelry/accessories/other | 94 | 26 | 0 | 1 | — | Rubber (1) |
| Watch Winders | Jewelry/accessories/other | 9 | 2 | 1 | 1 | Black,white (1) | Faux Leather (1) |
| Watches | Jewelry/accessories/other | 19 | 1 | 0 | 0 | — | — |
| Water & Stain Treatments | Jewelry/accessories/other | 5 | 4 | 1 | 1 | Clear (1) | Leather, Suede (1) |
| Water Shoes | Footwear | 168 | 12 | 2 | 1 | Purple (1); Mossy Green (1) | Other (1) |
| Weapons & Armor | Jewelry/accessories/other | 30 | 15 | 4 | 2 | Vintage (1); Black-green (1); Brown, Metallic (1) | Foam (1); 18 Gauge Steel (1) |
| Wear to Work | Clothing | 32 | 4 | 0 | 0 | — | — |
| Wedding & Engagement | Jewelry/accessories/other | 9 | 1 | 0 | 0 | — | — |
| Wedding Bands | Jewelry/accessories/other | 27 | 6 | 1 | 0 | Blue (1) | — |
| Wedding Dresses | Clothing | 9 | 5 | 0 | 0 | — | — |
| Wedding Rings | Jewelry/accessories/other | 47 | 15 | 0 | 0 | — | — |
| Western | Footwear, Jewelry/accessories/other | 95 | 20 | 0 | 0 | — | — |
| Westlake | Jewelry/accessories/other | 1136 | 73 | 1 | 1 | White (1) | Fabric (1) |
| Wide Leg Pants | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Wigs | Jewelry/accessories/other | 84 | 32 | 22 | 19 | Grey (2); Black (2); Red (2) | Synthetic (10); Synthetic Fiber (3); synthetic (2) |
| Wind & Rain | Clothing | 4 | 1 | 0 | 0 | — | — |
| Windbreakers | Clothing | 31 | 5 | 0 | 0 | — | — |
| Women | Clothing, Jewelry/accessories/other | 294 | 66 | 7 | 7 | Black (2); Multicolor (1); Red (1) | Cotton (3); Gemstone (1); Polyvinyl Chloride (1) |
| Women's Activewear Under $25 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Women's Apparel | Jewelry/accessories/other | 12 | 1 | 0 | 0 | — | — |
| Women's Boots Under $75 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Women's Comfort Shoes FA Test | Jewelry/accessories/other | 6 | 0 | 0 | 0 | — | — |
| Women's Dresses Under $25 | Jewelry/accessories/other | 5 | 0 | 0 | 0 | — | — |
| Women's Fall Boots | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Women's Festive Wear | Jewelry/accessories/other | 2 | 0 | 0 | 0 | — | — |
| Women's Halloween Costumes | Jewelry/accessories/other | 15 | 0 | 0 | 0 | — | — |
| Women's Maxi Dresses | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Women's Oversized Blazers for Fall | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Women's Plus-Size Apparel | Jewelry/accessories/other | 27 | 0 | 0 | 0 | — | — |
| Women's Romantic Loungewear | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Women's Sandal Markdowns | Jewelry/accessories/other | 5 | 1 | 0 | 0 | — | — |
| Women's Shoes | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Women's Summer-Ready Skirts | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Women's Sweaters Under $30 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Women's Sweaters Under $50 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Women's Swim Under $25 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Women's Swimwear | Jewelry/accessories/other | 16 | 2 | 0 | 0 | — | — |
| Women's leopard print dresses | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Women's sleepwear, swimwear, and more from Ekouaer and AI'MAGE | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Womens New Arrivals | Jewelry/accessories/other | 1 | 1 | 0 | 1 | — | Polyester (1) |
| Wool & Blends | Clothing | 23 | 3 | 0 | 0 | — | — |
| Wool & Pea Coats | Clothing | 39 | 6 | 0 | 0 | — | — |
| Work | Clothing | 114 | 5 | 0 | 0 | — | — |
| Work & Safety | Jewelry/accessories/other | 47 | 11 | 0 | 0 | — | — |
| Work Dresses Under $50 | Jewelry/accessories/other | 1 | 0 | 0 | 0 | — | — |
| Work Utility & Safety | Clothing | 7 | 1 | 0 | 0 | — | — |
| Workout Top & Bottom Sets | Clothing | 5 | 1 | 0 | 0 | — | — |
| Wrap | Jewelry/accessories/other | 38 | 5 | 4 | 3 | Yellow Citrine (1); Boho Wrap Bracelet (1); Red (1) | Leather (2); Seed Bead (1) |
| Wraps & Pashminas | Jewelry/accessories/other | 52 | 15 | 0 | 0 | — | — |
| Wrestling | Footwear | 12 | 1 | 0 | 0 | — | — |
| Wrist Watches | Jewelry/accessories/other | 1034 | 131 | 4 | 3 | Multi (1); Standard (1); White (1) | Blend (1); Resin (1); Titanium/Metal (1) |
| Wristlets | Bags | 42 | 7 | 2 | 1 | Black (1); 001 (1) | Leather (1) |
| Y-Necklaces | Jewelry/accessories/other | 23 | 7 | 0 | 0 | — | — |
| Yoga | Clothing | 36 | 0 | 0 | 0 | — | — |
