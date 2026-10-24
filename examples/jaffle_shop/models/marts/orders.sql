{{ config(materialized='table') }}

with payments as (
    select
        order_id,
        sum(amount) as amount
    from {{ ref('stg_payments') }}
    group by order_id
)

select
    o.order_id,
    o.customer_id,
    o.order_date,
    o.status,
    coalesce(p.amount, 0) as amount
from {{ ref('stg_orders') }} as o
left join payments as p on o.order_id = p.order_id
