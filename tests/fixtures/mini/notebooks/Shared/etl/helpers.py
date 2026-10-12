# Databricks notebook source
def clean(df):
    return df.dropDuplicates()


# COMMAND ----------

spark.sql("SELECT * FROM main.sales.orders_bronze LIMIT 10")
