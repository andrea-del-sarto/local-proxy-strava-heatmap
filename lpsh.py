from flask import Flask, Response
import requests

app = Flask(__name__)

# Permetti CORS
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

# Opzioni attività e colori
activities = ['all', 'run', 'ride', 'winter', 'water']
colors = ['hot', 'blue', 'bluered', 'purple', 'gray']

def choose_option(options, prompt, default_index=0):
    print(prompt)
    for i, opt in enumerate(options, start=1):
        default_mark = " (default)" if i-1 == default_index else ""
        print(f"{i} - {opt}{default_mark}")
    choice = input("Digita il numero (o lascia vuoto per valore di default): ").strip()
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(options):
            return options[idx]
    return options[default_index]  # default

# Scelte utente
activity = choose_option(activities, "Scegli attività:", default_index=0)
color = choose_option(colors, "Scegli colore:", default_index=0)  # hot è default

@app.route('/heatmap/<int:z>/<int:x>/<int:y>.png')
def heatmap(z, x, y):
    url = f'https://strava-heatmap.tiles.freemap.sk/{activity}/{color}/{z}/{x}/{y}.png?px=256'
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'https://www.freemap.sk/'
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        print(f"Tile richiesto: z={z}, x={x}, y={y}, activity={activity}, color={color}")
        return Response(r.content, content_type='image/png')
    except requests.RequestException as e:
        print(f"Errore tile z={z}, x={x}, y={y}: {e}")
        empty_tile = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x00\x00\x00\x01\x00\x08\x06\x00\x00\x00\x5c\x72\xa8\x66\x00\x00\x00\x0cIDATx\x9ccddbf\xa0\x040Q\xa4\x00\x00\x08\xfb\x01\xfd\xa7\x8c\x3e\x83\x00\x00\x00\x00IEND\xaeB`\x82'
        return Response(empty_tile, content_type='image/png')

if __name__ == '__main__':
    print(f"Server avviato con activity={activity} e color={color}")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
