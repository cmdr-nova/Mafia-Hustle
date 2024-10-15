from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import os
import random

app = Flask(__name__)



app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///mafia_hustle.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default_secret_key')
app.config['UPLOAD_FOLDER'] = 'static/uploads'
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    health = db.Column(db.Integer, default=100)
    money = db.Column(db.Integer, default=1000)
    items = db.Column(db.PickleType, default=[])
    level = db.Column(db.Integer, default=1)
    points = db.Column(db.Integer, default=0)
    kills = db.Column(db.Integer, default=0)
    prestige = db.Column(db.Integer, default=0)
    avatar = db.Column(db.String(200), nullable=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
@login_required
def index():
    return render_template('index.html', current_user=current_user)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        # Debugging statements
        print(f"Attempting login for user: {username}")
        if user:
            print(f"User found: {user.username}")
            if bcrypt.check_password_hash(user.password, password):
                print("Password match")
                login_user(user)
                return redirect(url_for('index'))
            else:
                print("Password does not match")
        else:
            print("User not found")
        
        flash('Login Unsuccessful. Please check username and password', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username')
    password = request.form.get('password')
    user = User.query.filter_by(username=username).first()
    if user:
        flash('Username already exists. Please choose a different one.', 'danger')
        return redirect(url_for('login'))
    
    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
    new_user = User(username=username, password=hashed_password)
    db.session.add(new_user)
    db.session.commit()
    
    # Debugging statement
    print(f"User created: {new_user.username}")
    
    flash('Account created successfully. Please log in.', 'success')
    return redirect(url_for('login'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/upload-avatar', methods=['POST'])
@login_required
def upload_avatar():
    if 'avatar' not in request.files:
        return jsonify({'success': False, 'error': 'No file part'})

    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No selected file'})

    if file:
        filename = f"{current_user.id}_avatar.png"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # Update the user's avatar URL in the database
        current_user.avatar = url_for('static', filename=f'uploads/{filename}')
        db.session.commit()

        return jsonify({'success': True})

    return jsonify({'success': False, 'error': 'File upload failed'})

@app.route('/api/player-info', methods=['GET'])
@login_required
def player_info():
    user = current_user
    return jsonify({
        'username': user.username,
        'health': round(user.health),
        'money': round(user.money),
        'level': round(user.level),
        'points': round(user.points),
        'kills': round(user.kills),
        'prestige': round(user.prestige)
    })

@app.route('/api/leaderboard', methods=['GET'])
def leaderboard():
    sorted_users = User.query.order_by(User.kills.desc(), User.points.desc()).limit(10).all()
    top_players = [{'username': user.username, 'kills': round(user.kills), 'points': round(user.points)} for user in sorted_users]
    return jsonify({'leaderboard': top_players})

@app.route('/api/attack', methods=['POST'])
@login_required
def attack():
    attacker_name = current_user.username
    defender_name = request.json.get('defender')
    attacker = User.query.filter_by(username=attacker_name).first()
    defender = User.query.filter_by(username=defender_name).first()
    if not attacker or not defender:
        return jsonify({'error': 'User not found'}), 404

    if attacker.health <= 0:
        return jsonify({'message': f'{attacker_name} is dead and cannot attack.'})
    if defender.health <= 0:
        return jsonify({'message': f'{defender_name} is already dead and cannot be attacked.'})

    damage = random.randint(5, 15)
    attacker.health -= damage
    if attacker.health < 0:
        attacker.health = 0

    defender.health -= 10
    if defender.health < 0:
        defender.health = 0
    if defender.health == 0:
        attacker.kills += 1

    attacker.points += 10
    level_up(attacker)

    db.session.commit()

    return jsonify({'message': f'{attacker_name} attacked {defender_name} and took {damage} damage. {attacker_name} gained 10 points.'})

@app.route('/api/run-job', methods=['POST'])
@login_required
def run_job():
    username = current_user.username
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({'error': 'User not found'}), 404

    if user.health <= 0:
        return jsonify({'message': f'{username} is dead and cannot run jobs.'})

    damage = random.randint(5, 15)
    user.health -= damage
    if user.health < 0:
        user.health = 0

    if user.health <= 0:
        return jsonify({'message': f'{username} failed the job and took {damage} damage. They have died.'})

    targets = User.query.filter(User.username != username).all()
    if not targets:
        return jsonify({'error': 'No other players to steal from'}), 400

    target = random.choice(targets)
    stolen_amount = random.randint(10, 100)

    user.money += stolen_amount
    target.money -= stolen_amount

    user.points += 10
    level_up(user)

    db.session.commit()

    return jsonify({'message': f'{username} stole ${stolen_amount} from ${target.username} and took ${damage} damage. ${username} gained 10 points.'})

@app.route('/api/heal-up', methods=['POST'])
@login_required
def heal_up():
    username = current_user.username
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({'error': 'User not found'}), 404

    found_food = random.choice([True, False])
    if found_food:
        heal_amount = random.randint(10, 30)
        user.health += heal_amount
        if user.health > 100 + (user.level - 1) * 10:
            user.health = 100 + (user.level - 1) * 10
        db.session.commit()
        if user.health >= 50:
            return jsonify({'message': f'{username} found food and healed ${heal_amount} health. They are now alive and can perform actions again.'})
        else:
            return jsonify({'message': f'{username} found food and healed ${heal_amount} health. They need to heal up to 50 health to perform actions.'})
    else:
        return jsonify({'message': f'{username} did not find any food.'})

@app.route('/api/logoff', methods=['POST'])
@login_required
def logoff():
    logout_user()
    return jsonify({'message': 'User logged off successfully'})

def level_up(user):
    if user.level < 60:
        points_needed = user.level * 100 * (1 + user.level / 10)
        if user.points >= points_needed:
            user.level += 1
            user.points -= points_needed
            user.health = 100 + (user.level - 1) * 10
    else:
        points_needed = 60 * 100 * (1 + 60 / 10) * (2 ** user.prestige)
        if user.points >= points_needed:
            user.prestige += 1
            user.points -= points_needed

if __name__ == '__main__':
    app.run(debug=True)
