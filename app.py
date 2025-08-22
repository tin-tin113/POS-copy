from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import os
from datetime import datetime
import uuid
import secrets 

app = Flask(__name__)
app.secret_key = os.environ.get('POS_SECRET_KEY', secrets.token_hex(16))

# Database initialization
def init_db():
    conn = sqlite3.connect('pos.db')
    cursor = conn.cursor()
    
    # Create products table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        stock INTEGER NOT NULL
    )
    ''')
    
    # Create sales table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sales (
        id TEXT PRIMARY KEY,
        date TEXT NOT NULL,
        total REAL NOT NULL
    )
    ''')
    
    # Create sale_items table with ON DELETE SET NULL for product references
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id TEXT NOT NULL,
        product_id INTEGER,
        product_name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        price REAL NOT NULL,
        FOREIGN KEY (sale_id) REFERENCES sales (id),
        FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE SET NULL
    )
    ''')

        # Insert default admin account
    cursor.execute("PRAGMA table_info(sale_items)")
    columns = cursor.fetchall()
    has_product_name = any(col[1] == 'product_name' for col in columns)
    
    if not has_product_name:
        try:
            cursor.execute("ALTER TABLE sale_items ADD COLUMN product_name TEXT")
            cursor.execute('''
            UPDATE sale_items 
            SET product_name = (SELECT name FROM products WHERE products.id = sale_items.product_id)
            WHERE product_name IS NULL
            ''')
        except sqlite3.OperationalError:
            pass

    
    cursor.execute('SELECT COUNT(*) FROM products')
    if cursor.fetchone()[0] == 0:
        sample_products = [
            ('Coffee', 3.50, 100),
            ('Tea', 2.50, 100),
            ('Sandwich', 5.99, 50),
        ]
        cursor.executemany('INSERT INTO products (name, price, stock) VALUES (?, ?, ?)', sample_products)
    
    conn.commit()
    conn.close()

# Initialize the database
init_db()





@app.route('/')
def index():
    return render_template('index.html')

@app.route('/pos')
def pos():
    conn = sqlite3.connect('pos.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM products WHERE stock > 0 ORDER BY name')
    products = cursor.fetchall()
    
    conn.close()
    
    if 'cart' not in session:
        session['cart'] = []
    
    return render_template('pos.html', products=products, cart=session['cart'])

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    product_id = int(request.form.get('product_id'))
    quantity = int(request.form.get('quantity', 1))
    
    if quantity <= 0:
        flash('Quantity must be greater than zero', 'error')
        return redirect(url_for('pos'))
    
    conn = sqlite3.connect('pos.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
    product = cursor.fetchone()
    
    if not product:
        flash('Product not found', 'error')
        return redirect(url_for('pos'))

    if 'cart' not in session:
        session['cart'] = []
    
    # Calculate how many of this product are already in the cart
    current_cart_quantity = 0
    for item in session['cart']:
        if item['id'] == product_id:
            current_cart_quantity = item['quantity']
            break
            
    # Check if we have enough stock including what's already in cart
    if product['stock'] < (quantity + current_cart_quantity):
        flash(f'Not enough stock. Only {product["stock"] - current_cart_quantity} more available.', 'error')
        return redirect(url_for('pos'))
    
    cart = session['cart']
    
    # Check if product is already in cart
    for item in cart:
        if item['id'] == product_id:
            item['quantity'] += quantity
            session['cart'] = cart
            flash(f'Added {quantity} more {product["name"]} to cart', 'success')
            return redirect(url_for('pos'))
    
    # If not in cart, add it
    cart.append({
        'id': product_id,
        'name': product['name'],
        'price': product['price'],
        'quantity': quantity
    })
    
    session['cart'] = cart
    flash(f'Added {product["name"]} to cart', 'success')
    
    conn.close()
    return redirect(url_for('pos'))

@app.route('/delete_product/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    conn = sqlite3.connect('pos.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT name FROM products WHERE id = ?', (product_id,))
        product_row = cursor.fetchone()
        
        if not product_row:
            flash('Product not found', 'error')
            conn.close()
            return redirect(url_for('products'))
        
        product_name = product_row[0]
        
        cursor.execute('UPDATE sale_items SET product_name = ? WHERE product_id = ? AND (product_name IS NULL OR product_name = "")', 
                      (product_name, product_id))
        
        # Now delete the product - foreign key constraint with ON DELETE SET NULL will handle references
        cursor.execute('DELETE FROM products WHERE id = ?', (product_id,))
        conn.commit()
        flash('Product deleted successfully', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting product: {str(e)}', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('products'))

@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    product_id = int(request.form.get('product_id'))
    
    # Fix #6: Consistent cart handling
    if 'cart' not in session:
        session['cart'] = []
        return redirect(url_for('pos'))
        
    cart = session['cart']
    cart = [item for item in cart if item['id'] != product_id]
    session['cart'] = cart
    
    flash('Item removed from cart', 'success')
    return redirect(url_for('pos'))

@app.route('/update_cart_item', methods=['POST'])
def update_cart_item():
    product_id = int(request.form.get('product_id'))
    quantity = int(request.form.get('quantity'))
    
    if quantity <= 0:
        flash('Quantity must be greater than zero', 'error')
        return redirect(url_for('pos'))
    
    if 'cart' not in session:
        session['cart'] = []
        return redirect(url_for('pos'))
        
    cart = session['cart']
    
    conn = sqlite3.connect('pos.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT stock FROM products WHERE id = ?', (product_id,))
    stock = cursor.fetchone()[0]
    

    current_cart_quantity = 0
    for item in cart:
        if item['id'] == product_id:
            current_cart_quantity = item['quantity']
            break
            
    # If updating to same amount, no need to check stock
    if current_cart_quantity == quantity:
        conn.close()
        return redirect(url_for('pos'))
            
    if stock < quantity:
        flash(f'Not enough stock. Only {stock} available.', 'error')
        conn.close()
        return redirect(url_for('pos'))
    
    for item in cart:
        if item['id'] == product_id:
            item['quantity'] = quantity
            break
    
    session['cart'] = cart
    flash('Cart updated', 'success')
    
    conn.close()
    return redirect(url_for('pos'))

@app.route('/checkout', methods=['POST'])
def checkout():
    if 'cart' not in session:
        session['cart'] = []
        
    cart = session['cart']
    
    if not cart:
        flash('Your cart is empty', 'error')
        return redirect(url_for('pos'))
    
    conn = sqlite3.connect('pos.db')
    cursor = conn.cursor()
    
    try:
        
        sale_id = str(uuid.uuid4())
        cursor.execute('SELECT id FROM sales WHERE id = ?', (sale_id,))
        while cursor.fetchone() is not None:
            sale_id = str(uuid.uuid4())
            cursor.execute('SELECT id FROM sales WHERE id = ?', (sale_id,))
        
        # Calculate total
        total = sum(item['price'] * item['quantity'] for item in cart)
        
        # Insert into sales table
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('INSERT INTO sales (id, date, total) VALUES (?, ?, ?)', 
                      (sale_id, now, total))
        
        # Insert sale items and update stock
        for item in cart:
            cursor.execute('INSERT INTO sale_items (sale_id, product_id, product_name, quantity, price) VALUES (?, ?, ?, ?, ?)',
                         (sale_id, item['id'], item['name'], item['quantity'], item['price']))
            
            cursor.execute('UPDATE products SET stock = stock - ? WHERE id = ?',
                         (item['quantity'], item['id']))
        
        conn.commit()
        
        # Clear cart after successful checkout
        session['cart'] = []
        
        flash('Checkout completed successfully!', 'success')
        
    except Exception as e:
        conn.rollback()
        flash(f'Error during checkout: {str(e)}', 'error')
    
    finally:
        conn.close()
    
    return redirect(url_for('pos'))

@app.route('/sales')
def sales():
    conn = sqlite3.connect('pos.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check for sales history data inconsistencies
    cursor.execute('''
    SELECT sales.id, sales.total as recorded_total,
           SUM(sale_items.price * sale_items.quantity) as calculated_total
    FROM sales
    LEFT JOIN sale_items ON sales.id = sale_items.sale_id
    GROUP BY sales.id
    HAVING ABS(recorded_total - calculated_total) > 0.01
    ''')
    
    inconsistent_sales = cursor.fetchall()
    
    if inconsistent_sales:
        flash('Warning: Some sales records have inconsistent totals. Please check the database.', 'warning')
    
    cursor.execute('''
    SELECT sales.id, sales.date, sales.total, 
           COUNT(sale_items.id) AS item_count
    FROM sales
    LEFT JOIN sale_items ON sales.id = sale_items.sale_id
    GROUP BY sales.id
    ORDER BY sales.date DESC
    ''')
    
    sales = cursor.fetchall()
    conn.close()
    
    return render_template('sales.html', sales=sales)

@app.route('/sale_details/<sale_id>')
def sale_details(sale_id):
    conn = sqlite3.connect('pos.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM sales WHERE id = ?', (sale_id,))
    sale = cursor.fetchone()
    
    if not sale:
        flash('Sale not found', 'error')
        return redirect(url_for('sales'))
    
    
    cursor.execute('''
    SELECT SUM(price * quantity) as calculated_total
    FROM sale_items
    WHERE sale_id = ?
    ''', (sale_id,))
    calculated_total = cursor.fetchone()['calculated_total'] or 0
    
    if abs(sale['total'] - calculated_total) > 0.01:
        flash(f'Warning: This sale has an inconsistent total. Recorded: {sale["total"]}, Calculated: {calculated_total}', 'warning')
    
    cursor.execute('''
    SELECT sale_items.*, 
           CASE WHEN products.name IS NULL THEN sale_items.product_name ELSE products.name END as name
    FROM sale_items
    LEFT JOIN products ON sale_items.product_id = products.id
    WHERE sale_items.sale_id = ?
    ''', (sale_id,))
    
    items = cursor.fetchall()
    

    deleted_products = False
    for item in items:
        if item['product_id'] is None:
            deleted_products = True
            break
    
    if deleted_products:
        flash('This sale contains products that have been deleted from the inventory.', 'info')
    
    conn.close()
    
    return render_template('sale_details.html', sale=sale, items=items)

@app.route('/products')
def products():
    conn = sqlite3.connect('pos.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM products ORDER BY name')
    products = cursor.fetchall()
    
    conn.close()
    
    return render_template('products.html', products=products)

@app.route('/add_product', methods=['GET', 'POST'])
def add_product():
    if request.method == 'POST':
        name = request.form.get('name')
        price = request.form.get('price', 0)
        stock = request.form.get('stock', 0)
        
        errors = []
        
        if not name or len(name.strip()) == 0:
            errors.append('Product name is required')
        elif len(name) > 100:  # Assuming a reasonable max length
            errors.append('Product name is too long (max 100 characters)')
            
        try:
            price = float(price)
            if price <= 0:
                errors.append('Price must be greater than zero')
        except ValueError:
            errors.append('Price must be a valid number')
            
        try:
            stock = int(stock)
            if stock < 0:
                errors.append('Stock cannot be negative')
        except ValueError:
            errors.append('Stock must be a valid number')
            
        if errors:
            for error in errors:
                flash(error, 'error')
            return redirect(url_for('add_product'))
        
        conn = sqlite3.connect('pos.db')
        cursor = conn.cursor()

        # Check if the product already exists by name
        cursor.execute('SELECT * FROM products WHERE name = ?', (name,))
        existing_product = cursor.fetchone()

        if existing_product:
            flash('This product already exists.', 'error')
            conn.close()
            return redirect(url_for('add_product'))

        # Insert new product into the database
        cursor.execute('INSERT INTO products (name, price, stock) VALUES (?, ?, ?)',
                       (name, price, stock))
        
        conn.commit()
        conn.close()

        flash('Product added successfully', 'success')
        return redirect(url_for('products'))

    return render_template('add_product.html')

@app.route('/edit_product/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    conn = sqlite3.connect('pos.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if request.method == 'POST':
        name = request.form.get('name')
        price = request.form.get('price', 0)
        stock = request.form.get('stock', 0)
        

        errors = []
        
        if not name or len(name.strip()) == 0:
            errors.append('Product name is required')
        elif len(name) > 100:
            errors.append('Product name is too long (max 100 characters)')
            
        try:
            price = float(price)
            if price <= 0:
                errors.append('Price must be greater than zero')
        except ValueError:
            errors.append('Price must be a valid number')
            
        try:
            stock = int(stock)
            if stock < 0:
                errors.append('Stock cannot be negative')
        except ValueError:
            errors.append('Stock must be a valid number')
            
        if errors:
            for error in errors:
                flash(error, 'error')
            return redirect(url_for('edit_product', product_id=product_id))
        
        # Check if another product already has this name
        cursor.execute('SELECT * FROM products WHERE name = ? AND id != ?', (name, product_id))
        existing_product = cursor.fetchone()
        
        if existing_product:
            flash('Another product with this name already exists.', 'error')
            return redirect(url_for('edit_product', product_id=product_id))
        
        cursor.execute('UPDATE products SET name = ?, price = ?, stock = ? WHERE id = ?',
                     (name, price, stock, product_id))
        
        # Update product name in any sale_items records
        cursor.execute('UPDATE sale_items SET product_name = ? WHERE product_id = ?', (name, product_id))
        
        conn.commit()
        flash('Product updated successfully', 'success')
        return redirect(url_for('products'))
    
    cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
    product = cursor.fetchone()
    
    if not product:
        flash('Product not found', 'error')
        return redirect(url_for('products'))
    
    conn.close()
    
    return render_template('edit_product.html', product=product)

@app.route('/clear_cart')
def clear_cart():
    session['cart'] = []
    flash('Cart cleared', 'success')
    return redirect(url_for('pos'))

if __name__ == '__main__':
    app.run(debug=True)