from finance_app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host=app.config.get("HOST", "127.0.0.1"), port=int(app.config.get("PORT", 5000)))
