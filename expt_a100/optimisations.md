### Prev: expt a2

### Optimisation 1

Rewrote T1 (Place Order) from a sequence of client-driven, per-item SQL
statements into one set-based SQL statement using data-modifying CTEs. The
previous implementation separately checked the customer, looked up each
product, reserved each item's inventory, generated IDs, inserted each order
item, and finally updated the order total. It used repeated `\gset` and nested
`\if` directives to pass every intermediate result back through pgbench. For a
multi-item order, this required many SQL executions and client/server protocol
round trips.

The new implementation constructs the requested one-to-five items as a small
relation and processes them as a set:

- `requested_items` selects the required number of generated item slots.
- `requirements` groups duplicate product selections and sums their quantities,
  so inventory for the same product is reserved once using the total required
  quantity.
- `eligible` checks the customer and verifies that every requested product and
  inventory row exists with sufficient stock.
- `reserved` updates the required inventory rows in one operation, while
  `reservation_ok` verifies that every requirement was updated.
- `inserted_order` calculates the total amount with `SUM(quantity * price)` and
  inserts the order only after reservation succeeds.
- `inserted_items` inserts all order items from the same requested-item
  relation.

This removes the five duplicated item-processing branches, replaces per-row
work with bulk joins, aggregation, update, and insert operations, and eliminates
the final order-total update by computing the total during the initial order
insert. It also avoids allocating order and order-item sequence values unless
the corresponding rows are inserted.

The validation and writes remain in a transaction and are connected through a
single statement. If the customer, a product, an inventory record, or the
required stock is unavailable, the statement creates no order or order items.
The expected performance improvement is lower statement parsing, planning,
network, and pgbench control-flow overhead, especially for orders containing
several items.