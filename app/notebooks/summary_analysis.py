# Notebook source
# COMMAND ----------
# MAGIC %md
# MAGIC # Summary Analysis
# MAGIC # Investigate the difference between two identical promt + LLMs for the same git commits
# MAGIC The Variance in some summaries will point us to points of interest.

# MAGIC Within this notebook we want to find point of interest in summaries in the summaries.csv. We are interested in summaries that ware showing differences between datasets. 


# MAGIC Each dataset are git commits with their diffs and with a summary of the diff. Points of interest are then summaries, that are different between datasets. 

# MAGIC Columns of the pandas dataframe (loaded from the csv)
# MAGIC Index(['Repo ID', 'commit hash', 'commit message', 'diff', 'PR message',
# MAGIC        'PR ID', 'semantic_summary'],
# MAGIC       dtype='str')

# MAGIC Step 1: We will find these points of interest by calculating the bigrams and encode them . 
# MAGIC Step 2: Next we will calculate the distance between the vectors of each summary encoding using several metrics. 
# MAGIC Step 3 : We will rank the vector distance column in decending order 

# MAGIC Add these steps to the notebook. Split the code into multiple cells. Small cells are good. 

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 1: Load the data

# COMMAND ----------
import pandas as pd

# COMMAND ----------
df = pd.read_csv('../summaries/experiment-01-03-26/summaries.csv')

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 2: Calculate bigrams and encode summaries

# COMMAND ----------
from sklearn.feature_extraction.text import CountVectorizer

def get_bigrams(text):
    if pd.isna(text):
        return []
    vectorizer = CountVectorizer(ngram_range=(2, 2))
    try:
        vectorizer.fit([text])
        return vectorizer.get_feature_names_out()
    except:
        return []

# COMMAND ----------
df['bigrams'] = df['semantic_summary'].apply(get_bigrams)

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 3: Encode bigrams as vectors

# COMMAND ----------
from sklearn.preprocessing import MultiLabelBinarizer

mlb = MultiLabelBinarizer()
bigram_matrix = mlb.fit_transform(df['bigrams'])
bigram_df = pd.DataFrame(bigram_matrix, columns=mlb.classes_, index=df.index)

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 4: Calculate distances between vectors using several metrics

# COMMAND ----------
from scipy.spatial.distance import cdist
import numpy as np

def calculate_distances(matrix, metric='cosine'):
    distances = cdist(matrix, matrix, metric=metric)
    return pd.DataFrame(distances, index=df.index, columns=df.index)

cosine_distances = calculate_distances(bigram_matrix, 'cosine')
euclidean_distances = calculate_distances(bigram_matrix, 'euclidean')

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 5: Rank vector distances in descending order

# COMMAND ----------
# MAGIC ### Cosine Distance Ranking

# COMMAND ----------
# Get upper triangle to avoid duplicates (i < j)
upper_triangle = np.triu_indices(len(df), k=1)
cosine_ranking = []
for i, j in zip(upper_triangle[0], upper_triangle[1]):
    cosine_ranking.append({
        'index_i': i,
        'index_j': j,
        'distance': cosine_distances.iloc[i, j],
        'summary_i': df.iloc[i]['semantic_summary'],
        'summary_j': df.iloc[j]['semantic_summary']
    })

cosine_ranking_df = pd.DataFrame(cosine_ranking).sort_values('distance', ascending=False)

# COMMAND ----------
# MAGIC ### Euclidean Distance Ranking

# COMMAND ----------
euclidean_ranking = []
for i, j in zip(upper_triangle[0], upper_triangle[1]):
    euclidean_ranking.append({
        'index_i': i,
        'index_j': j,
        'distance': euclidean_distances.iloc[i, j],
        'summary_i': df.iloc[i]['semantic_summary'],
        'summary_j': df.iloc[j]['semantic_summary']
    })

euclidean_ranking_df = pd.DataFrame(euclidean_ranking).sort_values('distance', ascending=False)

# COMMAND ----------
# MAGIC %md
# MAGIC ## Points of Interest
# MAGIC Summaries with highest distances are potential points of interest where datasets differ significantly.

# COMMAND ----------
print("Top 10 differences by Cosine Distance:")
print(cosine_ranking_df.head(10))

# COMMAND ----------
print("\nTop 10 differences by Euclidean Distance:")
print(euclidean_ranking_df.head(10))