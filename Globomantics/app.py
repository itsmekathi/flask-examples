from flask import Flask, jsonify, render_template, request, redirect, url_for, g, flash, send_from_directory
import sqlite3
from flask_wtf import FlaskForm, RecaptchaField
from flask_wtf.file import FileAllowed, FileRequired
from wtforms import StringField, TextAreaField, SubmitField, SelectField, DecimalField, FileField, HiddenField
from wtforms.validators import InputRequired, DataRequired, Length, ValidationError
from wtforms.widgets import Input
from werkzeug.utils import secure_filename, escape, unescape
from markupsafe import Markup
import pdb
import os
from datetime import datetime
from secrets import token_hex

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = "secretkey"
app.config["ALLOWED_IMAGE_EXTENSIONS"] = ["jpeg", "jpg", "png"]
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["IMAGE_UPLOADS"] = os.path.join(basedir, "uploads")
app.config["RECAPTCHA_PUBLIC_KEY"] = "6LcnU_AUAAAAAFDqrPo1E66uuU3JCfzullr5Sx2V"
app.config["RECAPTCHA_PRIVATE_KEY"] = "6LcnU_AUAAAAAFZkjSK9cEH4n6NJHEUFZbZRWJnp"
app.config["TESTING"] = True


class PriceInput(Input):
    input_type = "number"

    def __call__(self, field, **kwargs):
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("type", self.input_type)
        kwargs.setdefault("step", "0.01")
        if "value" not in kwargs:
            kwargs["value"] = field._value()
        if "required" not in kwargs and "required" in getattr(field, "flags", []):
            kwargs["required"] = True
        return Markup("""
            <div class="input-group mb-3">
                    <div class="input-group-prepend">
                        <span class="input-group-text">$</span>
                    </div>
                    <input %s>
                </div>""" % self.html_params(name=field.name, **kwargs))


class PriceField(DecimalField):
    widget = PriceInput()


class ItemForm(FlaskForm):
    title = StringField("Title", validators=[
                        InputRequired("Input is required!"),
                        DataRequired("Data is required!"),
                        Length(min=5, max=20, message="Input must be between 5 and 20 characters long")])
    price = PriceField("Price")
    description = TextAreaField("Description", validators=[
        InputRequired("Input is required!"),
        DataRequired("Data is required!"),
        Length(min=5, max=40, message="Input must be between 5 and 40 characters long")])
    image = FileField("Image", validators=[FileAllowed(
        app.config["ALLOWED_IMAGE_EXTENSIONS"], "Images only!")])


class BelongsToOtherFieldOptions:
    def __init__(self, table, belongs_to, foreign_key=None, message=None):
        if not table:
            raise AttributeError("""
        BelongsToOtherFieldOptions validator needs the table parameter
        """)
        if not belongs_to:
            raise AttributeError("""
        BelongsToOtherFieldOptions validator needs the belongs_to parameter
        """)
        self.table = table
        self.belongs_to = belongs_to

        if not foreign_key:
            foreign_key = belongs_to + "_id"
        if not message:
            message = "Choosen option is not valid"

        self.foreign_key = foreign_key
        self.message = message

    def __call__(self, form, field):
        c = get_db().cursor()
        try:
            c.execute(f"""SELECT COUNT(*) FROM {self.table}
            WHERE id = ? AND {self.foreign_key}=?""", (field.data, getattr(form, self.belongs_to).data))
        except Exception as e:
            raise AttributeError(f"""
        Passed parameters are not correct. {e}
        """)
        exists = c.fetchone()[0]
        if not exists:
            raise ValidationError(self.message)


def belongs_to_category(message):
    message = message

    def _belongs_to_category(form, field):
        c = get_db().cursor()
        c.execute(""" SELECT COUNT(*) FROM subcategories
                        WHERE id=? AND category_id=? """, (field.data, form.category.data))
        exists = c.fetchone()[0]
        if not exists:
            raise ValidationError(message)
    return _belongs_to_category


class NewItemForm(ItemForm):
    category = SelectField("Category", coerce=int)
    subcategory = SelectField(
        "Subcategory", coerce=int, validators=[BelongsToOtherFieldOptions(table='subcategories', belongs_to='category', message='Subcategory does not belong to that category.')])
    recaptcha = RecaptchaField()
    submit = SubmitField("Submit")


class EditItemForm(ItemForm):
    submit = SubmitField("Update item")


class DeleteItemForm(FlaskForm):
    submit = SubmitField("Delete item")


class FilterForm(FlaskForm):
    title = StringField("Title", validators=[Length(max=20)])
    price = SelectField("Price", coerce=int, choices=[
                        (0, "---"), (1, "Max to Min"), (2, "Min to max")])
    category = SelectField("Category", coerce=int)
    subcategory = SelectField("Subcategory", coerce=int)
    submit = SubmitField("Filter")


class NewCommentForm(FlaskForm):
    content = TextAreaField("Comment", validators=[InputRequired(
        "Input is required."), DataRequired("Data is required."), Length(min=5, max=20, message="Input must be between 5 and 20 characters long.")])
    item_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Submit")


@app.route('/comment/new', methods=["POST"])
def new_comment():
    conn = get_db()
    c = conn.cursor()
    form = NewCommentForm()
    try:
        is_ajax = int(request.form["ajax"])
    except:
        is_ajax = 0

    if form.validate_on_submit():
        c.execute(""" INSERT INTO comments (content, item_id) 
        VALUES(? , ?)""", (form.content.data, form.item_id.data,))
        conn.commit()
        if is_ajax:
            return render_template("_comment.html", content=form.content.data)
    if is_ajax:
        return "Content is required.", 400
    return redirect(url_for('item', item_id=form.item_id.data))


@app.route('/category/<int:category_id>')
def category(category_id):
    c = get_db().cursor()
    c.execute(""" SELECT id, name FROM subcategories
    where category_id = ?""", (category_id,))
    subcategories = c.fetchall()
    return jsonify(subcategories=subcategories)


@app.route('/item/<int:item_id>/edit', methods=["GET", "POST"])
def edit_item(item_id):
    conn = get_db()
    c = conn.cursor()
    item_from_db = c.execute("SELECT * FROM items WHERE id = ?", (item_id,))
    row = c.fetchone()
    try:
        item = {
            "id": row[0],
            "title": row[1],
            "description": row[2],
            "price": row[3],
            "image": row[4]
        }
    except:
        item = {}
    if item:
        form = EditItemForm()
        if form.validate_on_submit():
            filename = item["image"]
            if form.image.data:
                filename = save_image_upload(form.image)
            c.execute("""UPDATE items SET title = ?, description = ?, price =?, image=? WHERE id=?""",
                      (
                          escape(form.title.data),
                          escape(form.description.data),
                          float(form.price.data),
                          filename,
                          item_id,))
            conn.commit()
            flash(
                f"Item {form.title.data} has been successfully updated", "success")
            return redirect(url_for('item', item_id=item_id))
        form.title.data = item["title"]
        form.description.data = unescape(item["description"])
        form.price.data = item["price"]
        return render_template("edit_item.html", item=item, form=form)
    return redirect(url_for("home"))


@app.route("/item/<int:item_id>/delete", methods=["POST"])
def delete_item(item_id):
    conn = get_db()
    c = conn.cursor()
    item_from_db = c.execute("SELECT * FROM items WHERE id =?", (item_id,))
    row = c.fetchone()
    try:
        item = {
            "id": row[0],
            "title": row[1]
        }
    except:
        item = {}
    if item:
        c.execute("DELETE FROM items WHERE id=?", (item_id,))
        conn.commit()
        flash(
            f"Item {item['title']} has been successfully deleted.", "success")
    else:
        flash(f"This item does not exists.", "danger")
    return redirect(url_for("home"))


@app.route("/item/<int:item_id>")
def item(item_id):
    c = get_db().cursor()
    item_from_db = c.execute("""SELECT
    i.id, i.title, i.description, i.price, i.image, c.name, s.name
    FROM items as i
    INNER JOIN categories as c on c.id = i.category_id
    INNER JOIN subcategories as s on s.id = i.subcategory_id
    where i.id = ?""", (item_id,))
    row = c.fetchone()
    try:
        item = {
            'id': row[0],
            'name': row[1],
            'description': row[2],
            'price': row[3],
            'image': row[4],
            'category': row[5],
            'subcategory': row[6]
        }
    except:
        item = {
        }
    if item:
        comments_from_db = c.execute("""SELECT content FROM comments
                                WHERE item_id=? ORDER BY id DESC""", (item["id"],))
        comments = []
        for row in comments_from_db:
            comment = {
                "content": row[0]
            }
            comments.append(comment)
        commentForm = NewCommentForm()
        commentForm.item_id.data = item_id
        deleteItemForm = DeleteItemForm()
        return render_template("item.html", item=item, comments=comments, deleteItemForm=deleteItemForm, commentForm=commentForm)
    return redirect(url_for("home"))


@app.route("/")
def home():
    conn = get_db()
    c = conn.cursor()

    form = FilterForm(request.args, meta={"csrf": False})

    c.execute("select id, name FROM categories")
    categories = c.fetchall()
    categories.insert(0, (0, "---"))
    form.category.choices = categories

    c.execute("select id, name From subcategories")
    subcategories = c.fetchall()
    subcategories.insert(0, (0, "---"))
    form.subcategory.choices = subcategories

    query = """SELECT
    i.id, i.title, i.description, i.price, i.image, c.name, s.name
    FROM items as i
    INNER JOIN categories as c on c.id = i.category_id
    INNER JOIN subcategories as s on s.id = i.subcategory_id"""

    try:
        is_ajax = int(request.args["ajax"])
    except:
        is_ajax = 0

    if form.validate():
        filter_queries = []
        parameters = []

        if form.title.data.strip():
            filter_queries.append("i.title LIKE ?")
            parameters.append("%" + escape(form.title.data) + "%")
        if form.category.data:
            filter_queries.append("i.category_id = ?")
            parameters.append(form.category.data)
        if form.subcategory.data:
            filter_queries.append("i.subcategory_id = ?")
            parameters.append(form.subcategory.data)

        if filter_queries:
            query += " WHERE "
            query += " AND ".join(filter_queries)

        if form.price.data:
            if form.price.data == 1:
                query += " ORDER BY i.price DESC"
            else:
                query += " ORDER by i.price"
        else:
            query += " ORDER BY i.id DESC"
        items_from_db = c.execute(query, tuple(parameters))
        print(query)
    else:
        items_from_db = c.execute(query + " ORDER BY i.id DESC")
    items = []
    for row in items_from_db:
        item = {
            'id': row[0],
            'name': row[1],
            'description': row[2],
            'price': row[3],
            'image': row[4],
            'category': row[5],
            'subcategory': row[6]
        }
        items.append(item)
    if is_ajax:
        return render_template("_items.html", items=items)
    return render_template("home.html", items=items, form=form)


@app.route("/uploads/<filename>")
def uploads(filename):
    return send_from_directory(app.config["IMAGE_UPLOADS"], filename)


@app.route("/new-item", methods=["GET", "POST"])
def new_item():
    conn = get_db()
    c = conn.cursor()
    form = NewItemForm()
    c.execute("SELECT id, name From categories")
    categories = c.fetchall()
    # [(1, 'Food'), (2, 'Technology'),(2, 'Books')]
    form.category.choices = categories
    c.execute("SELECT id, name FROM subcategories")
    subcategories = c.fetchall()
    form.subcategory.choices = subcategories

    # pdb.set_trace()
    if form.validate_on_submit() and form.image.validate(form, extra_validators=(FileRequired(),)):
        filename = save_image_upload(form.image)
        c.execute("""INSERT INTO items (title, description, price, image, category_id, subcategory_id) VALUES(?,?,?,?,?,?)""",
                  (
                      escape(form.title.data),
                      escape(form.description.data),
                      float(form.price.data),
                      filename, form.category.data, form.subcategory.data))
        conn.commit()
        flash(
            f"Item {request.form.get('title')} has been successfully submitted", "success")
        return redirect(url_for('home'))
    return render_template("new_item.html", form=form)


def save_image_upload(image):
    format = "%Y%m%dT%H%M%S"
    now = datetime.utcnow().strftime(format)
    random_string = token_hex(2)
    filename = random_string + "_" + now + "_" + image.data.filename
    filename = secure_filename(filename)
    image.data.save(os.path.join(
        app.config["IMAGE_UPLOADS"], filename))
    return filename


def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect("db/globomantics.db")
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()
