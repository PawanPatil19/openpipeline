select
    c.customer_id,
    c.first_name,
    c.last_name,
    min(o.order_date) as first_order_date,
    count(o.order_id) as number_of_orders,
    sum(o.amount) as lifetime_value
from {{ ref('stg_customers') }} as c
left join {{ ref('orders') }} as o on c.customer_id = o.customer_id
group by c.customer_id, c.first_name, c.last_name
