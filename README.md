# Zepto Catalog Data Engineering Pipeline (`/data_pipeline`)

This pipeline scrapes, cleans, enriches, normalizes, and stores live catalog pricing and availability data from `books.toscrape.com` into an SQLite database for competitive intelligence benchmarking.

## 1. Pipeline Architecture

1. **Scraping (`BeautifulSoup` & `requests`):** Fetches 5 paginated listing pages (100 book items) capturing `title`, `price_str`, `rating_text`, `availability_text`, and `category`.
2. **Cleaning & Defensive Handling:** 
   - Strips currency symbols (`£`) and casts prices to `float`.
   - Maps textual star ratings (`One`..`Five`) to integer ratings ($1–5$).
   - Parses text availability string into a binary `in_stock` boolean flag ($1/0$).
   - **Imputation Strategy:** Any unparseable numeric entries are imputed using column medians, ensuring pipeline failure prevention without discarding complete records unnecessarily.
3. **Currency Conversion:** Applies project fixed baseline conversion rate:
   $$\text{Price (INR)} = \text{Price (GBP)} \times 105.50$$
   *(1 GBP = 105.50 INR fixed project-defined baseline rate, requiring no external API lookup).*
4. **Relational Database (`catalog.db`):** Normalized 2-table SQLite relational database enforcing Primary Key / Foreign Key constraints.

---

## 2. Relational Database Schema

```sql
CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_name TEXT NOT NULL UNIQUE
);

CREATE TABLE books (
    book_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    price_gbp REAL NOT NULL,
    price_inr REAL NOT NULL,
    rating INTEGER NOT NULL,
    in_stock INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    FOREIGN KEY (category_id) REFERENCES categories(category_id)
);