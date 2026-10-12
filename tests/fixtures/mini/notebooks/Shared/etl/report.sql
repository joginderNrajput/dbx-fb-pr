-- Databricks notebook source
CREATE OR REPLACE VIEW main.sales.v_orders AS
SELECT o.*, c.name FROM main.sales.orders o JOIN main.crm.customers c ON o.cid = c.id;

-- COMMAND ----------

OPTIMIZE main.sales.orders ZORDER BY (order_date);
