# Databricks notebook source
# MAGIC %md
# MAGIC # Ingest orders (sample fixture)

# COMMAND ----------

dbutils.widgets.text("run_date", "")
run_date = dbutils.widgets.get("run_date")
key = dbutils.secrets.get(scope="kv-sales", key="storage-key")
spark.conf.set("fs.azure.account.key.salesdl.dfs.core.windows.net", key)

# COMMAND ----------

df = (
    spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "json")
    .load("/mnt/raw/orders")
)

# COMMAND ----------

# MAGIC %run ./helpers

# COMMAND ----------

df.writeStream.toTable("main.sales.orders_bronze")
