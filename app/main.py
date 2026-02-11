from etl_pipeline import extract_and_transform, write_to_csv


def main():
    """Run the ETL pipeline to extract and combine commits, PRs, and diffs."""
    print("Starting ETL pipeline...")
    
    # Extract and transform data
    rows = extract_and_transform()
    print(f"Extracted and transformed {len(rows)} rows.")
    
    # Write to CSV
    write_to_csv(rows)
    print("ETL pipeline completed successfully!")


if __name__ == "__main__":
    main()
