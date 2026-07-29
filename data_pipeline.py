import re
import sqlite3
import pandas as pd
import requests
from bs4 import BeautifulSoup

# ==============================================================================
# CONFIGURATION & CONSTANTS
# ==============================================================================
BASE_URL = "https://books.toscrape.com/catalogue/page-{}.html"
FIXED_GBP_TO_INR_RATE = 105.50  # Required fixed project baseline rate
DB_PATH = "catalog.db"

RATING_MAP = {
    "One": 1,
    "Two": 2,
    "Three": 3,
    "Four": 4,
    "Five": 5
}

# ==============================================================================
# TASK 1: SCRAPING (5 PAGINATED LISTING PAGES -> 100 BOOKS)
# ==============================================================================
def scrape_catalog(num_pages=5):
    """
    Scrapes book listings across multiple paginated pages on books.toscrape.com.
    Captures: title, price_str, star_rating_text, availability_text, category.
    """
    raw_data = []
    
    for page in range(1, num_pages + 1):
        url = BASE_URL.format(page)
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, "html.parser")
        products = soup.select("article.product_pod")
        
        for p in products:
            # Title
            title = p.h3.a["title"].strip()
            
            # Price
            price_text = p.select_one("p.price_color").get_text(strip=True)
            
            # Star Rating (Extracted from CSS class e.g., "star-rating Three")
            rating_classes = p.select_one("p.star-rating")["class"]
            rating_text = [c for c in rating_classes if c != "star-rating"][0]
            
            # Availability
            avail_text = p.select_one("p.instock.availability").get_text(strip=True)
            
            # Category (Default to 'General Catalogue' for main paginated listings)
            category = "General Catalogue"
            
            raw_data.append({
                "title": title,
                "price_str": price_text,
                "rating_text": rating_text,
                "availability_text": avail_text,
                "category": category
            })
            
    print(f"[SUCCESS] Scraped {len(raw_data)} items across {num_pages} catalog pages.")
    return pd.DataFrame(raw_data)


# ==============================================================================
# TASK 2: CLEANING & CURRENCY CONVERSION
# ==============================================================================
def clean_and_enrich(df_raw):
    """
    Cleans raw web fields:
    - Extracts price_gbp float by stripping currency symbols
    - Maps text star ratings to integers (1-5)
    - Parses stock status to boolean (1/0)
    - Enriches price_inr using fixed rate 105.50 INR/GBP
    Handles messy rows via robust median imputation fallback.
    """
    df = df_raw.copy()
    
    # 1. Clean Price GBP
    def parse_price(val):
        try:
            cleaned = re.sub(r'[^\d.]', '', str(val))
            return float(cleaned)
        except Exception:
            return None

    df["price_gbp"] = df["price_str"].apply(parse_price)
    
    # Fallback Imputation if any price fails to parse
    if df["price_gbp"].isnull().any():
        median_price = df["price_gbp"].median()
        df["price_gbp"].fillna(median_price, inplace=True)
        print(f"[IMPUTATION] Applied median price ({median_price}) to corrupt price values.")

    # 2. Convert Rating Text -> Integer (1 to 5)
    df["rating"] = df["rating_text"].map(RATING_MAP).fillna(3).astype(int)

    # 3. Parse Availability -> Boolean (1 for In Stock, 0 for Out of Stock)
    df["in_stock"] = df["availability_text"].str.contains("In stock", case=False, na=False).astype(int)

    # 4. Fixed Baseline Currency Conversion (1 GBP = 105.50 INR)
    df["price_inr"] = (df["price_gbp"] * FIXED_GBP_TO_INR_RATE).round(2)

    cleaned_df = df[["title", "price_gbp", "price_inr", "rating", "in_stock", "category"]]
    print(f"[SUCCESS] Cleaned and enriched dataset shape: {cleaned_df.shape}")
    return cleaned_df


# ==============================================================================
# TASK 3: NORMALIZED SQLITE SCHEMA & STORAGE
# ==============================================================================
def create_and_load_db(df_cleaned, db_path=DB_PATH):
    """
    Sets up a normalized 2-table schema in SQLite with Primary Key / Foreign Key relationship:
    - categories (category_id PK, category_name UNIQUE)
    - books (book_id PK, title, price_gbp, price_inr, rating, in_stock, category_id FK)
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Enable Foreign Key Enforcement
    cursor.execute("PRAGMA foreign_keys = ON;")

    # Drop existing tables for idempotent execution
    cursor.execute("DROP TABLE IF EXISTS books;")
    cursor.execute("DROP TABLE IF EXISTS categories;")

    # Create Normalized Tables
    cursor.execute("""
        CREATE TABLE categories (
            category_id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT NOT NULL UNIQUE
        );
    """)

    cursor.execute("""
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
    """)

    # Populate categories
    categories = df_cleaned["category"].unique()
    for cat in categories:
        cursor.execute("INSERT INTO categories (category_name) VALUES (?);", (cat,))

    # Retrieve category map
    cursor.execute("SELECT category_name, category_id FROM categories;")
    cat_map = dict(cursor.fetchall())

    # Map category_id into dataframe
    df_db = df_cleaned.copy()
    df_db["category_id"] = df_db["category"].map(cat_map)

    # Insert Books
    books_data = df_db[["title", "price_gbp", "price_inr", "rating", "in_stock", "category_id"]].to_tuples()
    cursor.executemany("""
        INSERT INTO books (title, price_gbp, price_inr, rating, in_stock, category_id)
        VALUES (?, ?, ?, ?, ?, ?);
    """, books_data)

    conn.commit()
    conn.close()
    print(f"[SUCCESS] Loaded data into SQLite database '{db_path}'.")


# Helper extension to convert DataFrame to tuples
pd.DataFrame.to_tuples = lambda self: [tuple(x) for x in self.values]


# ==============================================================================
# TASK 4 & 5: SQL QUERIES & PANDAS EQUIVALENCE VERIFICATION
# ==============================================================================
def execute_sql_and_verify(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    
    print("\n" + "="*80)
    print("EXECUTING 5 SQL QUERIES (COVERING SELECT, WHERE, ORDER BY, LIMIT, DISTINCT, IN, JOIN)")
    print("="*80)

    # Query 1: SELECT, WHERE, IN
    q1 = """
        SELECT title, rating, price_gbp 
        FROM books 
        WHERE rating IN (4, 5) 
        LIMIT 5;
    """
    df_q1 = pd.read_sql(q1, conn)
    print("\n--- Query 1: Top Rated Books (rating IN (4, 5)) ---")
    print(df_q1.to_string(index=False))

    # Query 2: DISTINCT, ORDER BY
    q2 = """
        SELECT DISTINCT rating 
        FROM books 
        ORDER BY rating DESC;
    """
    df_q2 = pd.read_sql(q2, conn)
    print("\n--- Query 2: Distinct Ratings Available ---")
    print(df_q2.to_string(index=False))

    # Query 3: WHERE, BETWEEN, ORDER BY, LIMIT
    q3 = """
        SELECT title, price_inr 
        FROM books 
        WHERE price_inr BETWEEN 2000.0 AND 5000.0 
        ORDER BY price_inr ASC 
        LIMIT 5;
    """
    df_q3 = pd.read_sql(q3, conn)
    print("\n--- Query 3: Books priced between ₹2,000 and ₹5,000 ---")
    print(df_q3.to_string(index=False))

    # Query 4: Aggregation with WHERE
    q4 = """
        SELECT count(*) AS total_in_stock, round(avg(price_inr), 2) AS avg_price_inr 
        FROM books 
        WHERE in_stock = 1;
    """
    df_q4 = pd.read_sql(q4, conn)
    print("\n--- Query 4: Stock Summary Statistics ---")
    print(df_q4.to_string(index=False))

    # Query 5: REQUIRED JOIN Query
    q5 = """
        SELECT b.book_id, b.title, c.category_name, b.rating, b.price_gbp, b.price_inr
        FROM books b
        JOIN categories c ON b.category_id = c.category_id
        WHERE b.rating = 5
        ORDER BY b.price_inr DESC
        LIMIT 5;
    """
    df_sql_join = pd.read_sql(q5, conn)
    print("\n--- Query 5 (JOIN Query via SQL): Top 5 Priced 5-Star Books with Category ---")
    print(df_sql_join.to_string(index=False))

    # --------------------------------------------------------------------------
    # PANDAS EQUIVALENCE REPRODUCTION FOR JOIN QUERY
    # --------------------------------------------------------------------------
    books_df = pd.read_sql("SELECT * FROM books;", conn)
    categories_df = pd.read_sql("SELECT * FROM categories;", conn)
    conn.close()

    # Perform pandas pd.merge equivalent
    merged_df = pd.merge(books_df, categories_df, on="category_id")
    df_pd_join = (
        merged_df[merged_df["rating"] == 5]
        .sort_values(by="price_inr", ascending=False)
        .head(5)[["book_id", "title", "category_name", "rating", "price_gbp", "price_inr"]]
        .reset_index(drop=True)
    )

    print("\n" + "="*80)
    print("PANDAS pd.merge EQUIVALENCE CHECK FOR QUERY 5")
    print("="*80)
    print(df_pd_join.to_string(index=False))

    # Verification assertion
    pd.testing.assert_frame_equal(df_sql_join, df_pd_join)
    print("\n[VERIFICATION SUCCESS] pd.read_sql and pd.merge outputs match identically!")


if __name__ == "__main__":
    raw_data = scrape_catalog(num_pages=5)
    cleaned_data = clean_and_enrich(raw_data)
    create_and_load_db(cleaned_data)
    execute_sql_and_verify()