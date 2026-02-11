from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Radi! Bautagesbericht app (v1)"

if __name__ == "__main__":
    app.run()
