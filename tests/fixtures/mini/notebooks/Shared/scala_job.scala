// Databricks notebook source
val df = spark.read.format("delta").load("dbfs:/FileStore/tables/x")
display(df)
