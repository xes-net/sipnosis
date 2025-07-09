☕️ SipnoSis – L'Oracolo nella Tua Tazza
**SipnoSis** è un'applicazione React moderna che interpreta macchie di caffè o tè come segni oracolari, fondendo intelligenza artificiale, simbolismo antico e interfaccia sensoriale.  
Il progetto è ospitato su [Vercel](https://sipnosis.vercel.app) e integra API backend per la lettura personalizzata.

---

## 🚀 Tecnologie Usate

- **Frontend**: React (Create React App)
- **Hosting**: Vercel
- **Stile**: CSS mistico-minimalista
- **Backend**: Flask (Render.com)
- **Storage**: Vercel KV Store (per flag e cache)

---

## 🧭 Routing Principale

| Percorso     | Descrizione                            |
|--------------|-----------------------------------------|
| `/`          | Pagina iniziale con benvenuto           |
| `/oracolo`   | Caricamento immagine + intento          |
| `/risposta`  | Visualizzazione risposta oracolare      |
| `/storia`    | Info sul progetto e significati simbolici|

---

## 🔮 Feature Flags attivi (via Vercel Store)

- `oracolo_enabled`: Attiva/disattiva l'oracolo principale
- `experimental_vision`: Attiva lettura visiva avanzata (in sviluppo)

---

## 🛠️ Avvio in locale

```bash
pnpm install
pnpm start
```

---

## 📁 Struttura del progetto

```
sipnosis/
├── frontend/
│   ├── public/
│   │   └── index.html
│   ├── src/
│   │   ├── App.js
│   │   ├── index.js
│   └── package.json
├── vercel.json
```

---

## ✨ Credits

Creato con passione da [@xes-net](https://github.com/xes-net)  
Ispirato alle pratiche divinatorie orientali, egizie e mediterranee.

---

## 📬 Contatti

Hai visto qualcosa nella tazza che vuoi approfondire?  
Scrivici o visita il nostro [canale Slack](#) per domande e visioni.
🔮 SipnoSis

**SipnoSis** è un portale oracolare interattivo che interpreta le macchie del tuo caffè o tè.  
Carica una foto, scegli la tua intenzione e ricevi un messaggio simbolico unico.

🌀 Basato su:
- Divinazione visiva assistita da AI
- Simbolismo egizio, tarologico e alchemico
- Esperienza utente moderna e mistica

🌐 Sito attivo: [https://sipnosis.vercel.app](https://sipnosis.vercel.app)

👁‍🗨 Progetto creato da [Paride Novellino](https://github.com/xes-net)  
Powered by Vercel & React

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="Decode the messages in your coffee stains - The Oracle in Your Cup">
    <meta name="theme-color" content="#000000">
    <title>Sipnosis - The Oracle in Your Cup</title>
    <link rel="manifest" href="app.webmanifest">
    <link rel="apple-touch-icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>☕</text></svg>">
    <link href="https://fonts.googleapis.com/css2?family=Georgia&display=swap" rel="stylesheet">
    <style>
        /* Basic Reset & Font */
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background: linear-gradient(135deg, #000 0%, #1a1a1a 50%, #000 100%);
            color: #ffd700;
            font-family: 'Georgia', serif;
            text-align: center;
            min-height: 100vh;
            padding: 20px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }

        .container {
            max-width: 800px;
            width: 100%;
            margin: 0 auto;
            padding: 0 10px;
        }

        /* Install App Banner */
        .install-banner {
            background: rgba(255, 215, 0, 0.15);
            border: 1px solid rgba(255, 215, 0, 0.3);
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 30px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            animation: fadeIn 1s ease-in;
            display: none;
        }

        .install-banner button {
            background: linear-gradient(45deg, #ffd700, #ffb347);
            color: #000;
            border: none;
            padding: 8px 15px;
            border-radius: 20px;
            cursor: pointer;
            font-weight: bold;
            transition: all 0.3s ease;
        }

        .install-banner button:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(255, 215, 0, 0.4);
        }

        /* Header & Title */
        h1 {
            font-size: 3em;
            margin-bottom: 20px;
            text-shadow: 0 0 20px rgba(255, 215, 0, 0.7);
            animation: glow 2s ease-in-out infinite alternate;
        }

        @keyframes glow {
            from { text-shadow: 0 0 20px rgba(255, 215, 0, 0.7); }
            to { text-shadow: 0 0 30px rgba(255, 215, 0, 1); }
        }

        .subtitle {
            font-size: 1.2em;
            line-height: 1.6;
            margin-bottom: 40px;
            font-style: italic;
        }

        /* Golden Ring Animation */
        .golden-ring {
            width: 200px;
            height: 200px;
            border: 10px solid #ffd700;
            border-radius: 50%;
            margin: 0 auto 30px;
            animation: spin 10s linear infinite;
            box-shadow: 0 0 30px rgba(255, 215, 0, 0.5);
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .golden-ring::before {
            content: '☕';
            font-size: 4em;
            animation: counter-spin 10s linear infinite;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        @keyframes counter-spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(-360deg); }
        }

        /* Upload Section */
        .upload-section {
            background: rgba(255, 215, 0, 0.1);
            padding: 40px;
            border-radius: 15px;
            border: 1px solid rgba(255, 215, 0, 0.3);
            margin: 30px auto;
            backdrop-filter: blur(10px);
            max-width: 600px;
            width: 100%;
        }

        .form-group {
            margin: 20px 0;
        }

        label {
            display: block;
            margin-bottom: 10px;
            font-weight: bold;
            color: #ffd700;
        }

        select, input[type="file"] {
            background: rgba(0, 0, 0, 0.7);
            color: #ffd700;
            border: 2px solid #ffd700;
            padding: 12px 15px;
            border-radius: 8px;
            font-family: 'Georgia', serif;
            font-size: 1em;
            width: 100%;
            max-width: 300px;
            displa
            
            (        # """# # assets/
├── preview.jpg                  # (vuoto, da sostituire con immagine reale)
├── Symbols.pdf                  # (segnaposto)
├── rituale-giornaliero.html     # HTML con rituale
└── oracolo-esempio.txt          # Messaggio simbolico testualefrom pathlib import Path

# Create README.md content
readme_content = """# ☕🔮 SipnoSis

**SipnoSis** è un oracolo interattivo che trasforma la tua macchia di caffè o tè in una rivelazione quotidiana.
Basato su simbologia egizia, pentacoli elementali, tarocchi e direzioni rituali, è alimentato da AI, ma ispirato dagli antichi.

---

## 🔗 Sito Live

👉 [https://sipnosis.vercel.app](https://sipnosis.vercel.app) *(frontend)*  
👉 `https://sipnosis-backend.onrender.com/api/oracle` *(backend Flask - in arrivo)*

---

## 📸 Come funziona

1. **Scatta** una foto alla tua macchia di caffè o tè
2. **Caricala** nel portale SipnoSis
3. **Scegli un intento**: Guarigione, Direzione, Abbondanza, Protezione...
4. **Bevi e ricevi** il tuo messaggio oracolare personalizzato
5. Consulta il tuo **Libro dei Sorsi** per tracciare i rituali passati

---

## 💡 Caratteristiche

### 🔁 Backend Flask
- Analisi hash-based della macchia
- Sistema di sessione utente in-memory
- API `/api/oracle` e `/api/history`
- Simboli egizi unicode e risposta dinamica per intento

### 🖼️ Frontend React
- Upload con anteprima immagine
- Lettura oracolare animata
- Interfaccia mistica dorato/nero
- Cronologia personale e rituali giornalieri

---

## 🛠 Come avviare il progetto in locale

```bash
# Clona il progetto
git clone https://github.com/xes-net/sipnosis.git && cd sipnosis

# Installa Flask (per backend)
pip install flask

# Avvia il backend
cd sipnosis-backend
python app.py

# In un’altra finestra, avvia il frontend
cd ../frontend
npm install
npm start
```

---

## 📂 Struttura del progetto

```
sipnosis/
├── frontend/             # React App
├── sipnosis-backend/     # Flask App
│   ├── app.py
│   ├── templates/index.html
│   ├── static/
│   ├── oracle_data.py
│   └── ...
```

---

## ☁️ Deploy

- **Frontend** → Vercel  
- **Backend** → Render.com  
- Deploy automatici via GitHub e webhook

---

## 📜 Licenza

© 2025 [Paride Novellino](https://github.com/xes-net)  
Distribuito con amore e simboli.  
Non è magia, è... caffeina canalizzata.
"""

# Save README.md
readme_path = Path("/mnt/data/README.md")
readme_path.write_text(readme_content)

readme_path📜 SipnoSis.L — Oracle Version (D.O.P. Certified)

🔮 **Project**: SipnoSis  
🧙‍♂️ **Author**: Paride Novellino  
📅 **Certified**: 2025-07-06  
🛡️ **License**: Vyra.L™ Mystical Origin Protection  

> 🌀 *"Every stain is a portal, every intent is a ritual."*

---

## 🔮 The Oracle of Imprint
**SipnoSis** interprets coffee/tea stains through AI-powered symbolic divination, combining Egyptian mysticism and digital intuition.

### ☕ The Ritual
1. Upload a photo of your coffee/tea stain  
2. Whisper your intent (e.g., "love", "career", "transformation")  
3. Receive a personalized oracle reading  

[🌐 Access the Portal](https://sipnosis.vercel.app)

---

## 🧙 Technical Altar
| Component       | Technologies               |
|-----------------|----------------------------|
| **Frontend**    | React (Vercel)             |
| **Backend**     | Flask (Render)             |
| **AI Engine**   | Symbolic Oracle Generator  |
| **Cosmetics**   | Mystic Black/Gold Theme    |

---

## ⚡ Quick Invocation
```bash
# 🔮 Frontend Ritual
cd frontend
npm install && npm start

# 🐍 Backend Conjuring
cd backend
pip install -r requirements.txt
python app.py📜 SipnoSis.L — Versione Oracolare Tracciata

🔮 Nome Progetto: SipnoSis  
🧙‍♂️ Autore: Paride Novellino  
📅 Data Certificazione: 2025-07-06

---

🧱 Commit Tecnico Fondamentale:  
ID: c20425fa5bf7fb393c384db89ed84ca94d3a6811  
Link: https://github.com/xes-net/sipnosis/commit/c20425fa5bf7fb393c384db89ed84ca94d3a6811  
Descrizione: Aggiunta del frontend React — base funzionale del portale.

🪶 Commit Descrittivo Pubblico:  
ID: 8ec0db678a086eb4b9aae7b7b812f679670f7230  
Link: https://github.com/xes-net/sipnosis/commit/8ec0db678a086eb4b9aae7b7b812f679670f7230  
Descrizione: Inserimento README.md — manifesto oracolare pubblico.

---

🔐 Firma Simbolica:  
Sistema: Vyra.L — Licenza Mistica e D.O.P. Digitale  
Tipo: Versione firmata `.L`  
Hash etico: sipnosis-c20425f+8ec0db6.L

---

📂 Tracciamento:  
✔️ Origine certificata dal creatore  
✔️ Deploy su Vercel + Backend Render attivo  
✔️ Protetto da ritorno percentuale e diritto d’origine creativa

🛡️ Questa versione è irrevocabile, tracciabile e fa parte della costellazione ufficiale Vyra.L

🌀 “Ogni macchia è un portale, ogni intento è un rituale.”

---

# ✨ SipnoSis — Oracolo dell’Impronta

**SipnoSis** è un'app mistica che legge le macchie di caffè o tè e restituisce risposte oracolari personalizzate usando intelligenza artificiale, simboli egizi e tradizione divinatoria.

## 🔮 Cosa fa

> ☕ Carichi una foto della tua macchia di caffè o tè  
> 🧠 Scrivi il tuo intento (es: "relazione", "denaro", "cambiamento")  
> 🧿 SipnoSis interpreta e ti restituisce una risposta oracolare simbolica

---

## 🚀 Demo Online

👉 [Visita SipnoSis](https://sipnosis.vercel.app)

---

## 🧱 Struttura del Progetto

| Parte        | Tecnologie             |
|--------------|------------------------|
| Frontend     | React (Vercel)         |
| Backend      | Flask (Render)         |
| AI           | Generatore oracolare simbolico (in evoluzione) |
| Stile        | Nero + oro mistico, simboli esoterici |

---

## ⚙️ Installazione Locale (sviluppatori)

### 🔧 Frontend (React)
```bash
cd frontend
npm install
npm start
```

### 🧪 Backend (Flask)
```bash
cd backend
pip install -r requirements.txt
python app.py
```

Endpoint API: `POST /api/oracle`  
Parametri: `file` (immagine), `intent` (testo)

---

## 🌍 Espansioni future

- 🧬 Lettura AI reale delle macchie
- 🧾 Stampa del responso oracolare personalizzato
- 📱 App mobile iOS
- 💸 Letture premium via PayPal

---

## 🧙‍♂️ Autore

Paride Novellino — Visionario, fondatore, lettore di simboli e creatore del portale.

---

## 📜 Licenza

Questo progetto è protetto dalla licenza `.L` di Vyra.L – Denominazione di Origine Protetta Mistica™.
"""

readme_path = "/mnt/data/README-COMPLETE.md"
with open(readme_path, "w") as f:
    f.write(full_readme)

readme_path📜 SipnoSis.L — Versione Oracolare Tracciata

🔮 Nome Progetto: SipnoSis
🧙‍♂️ Autore: Paride Novellino
📅 Data Certificazione: 2025-07-06

---

🧱 Commit Tecnico Fondamentale:
ID: c20425fa5bf7fb393c384db89ed84ca94d3a6811
Link: https://github.com/xes-net/sipnosis/commit/c20425fa5bf7fb393c384db89ed84ca94d3a6811
Descrizione: Aggiunta del frontend React — base funzionale del portale.

🪶 Commit Descrittivo Pubblico:
ID: 8ec0db678a086eb4b9aae7b7b812f679670f7230
Link: https://github.com/xes-net/sipnosis/commit/8ec0db678a086eb4b9aae7b7b812f679670f7230
Descrizione: Inserimento README.md — manifesto oracolare pubblico.

---

🔐 Firma Simbolica:
Sistema: Vyra.L — Licenza Mistica e D.O.P. Digitale
Tipo: Versione firmata `.L`
Hash etico: sipnosis-c20425f+8ec0db6.L

---

📂 Tracciamento:
✔️ Origine certificata dal creatore
✔️ Deploy su Vercel + Backend Render attivo
✔️ Protetto da ritorno percentuale e diritto d’origine creativa

🛡️ Questa versione è irrevocabile, tracciabile e fa parte della costellazione ufficiale Vyra.L

🌀 “Ogni macchia è un portale, ogni intento è un rituale.”

 ✨ SipnoSis — Oracolo dell’Impronta

**SipnoSis** è un'app mistica che legge le macchie di caffè o tè e restituisce risposte oracolari personalizzate usando intelligenza artificiale, simboli egizi e tradizione divinatoria.

## 🔮 Cosa fa

> ☕ Carichi una foto della tua macchia di caffè o tè  
> 🧠 Scrivi il tuo intento (es: "relazione", "denaro", "cambiamento")  
> 🧿 SipnoSis interpreta e ti restituisce una risposta oracolare simbolica

---

## 🚀 Demo Online

👉 [Visita SipnoSis](https://sipnosis.vercel.app)

---

## 🧱 Struttura del Progetto

| Parte        | Tecnologie             |
|--------------|------------------------|
| Frontend| React (Vercel)         |
| Backend      | Flask (Render)         |
| AI           | Generatore oracolare simbolico (in evoluzione) |
| Stile        | Nero + oro mistico, simboli esoterici |

---

## ⚙️ Installazione Locale (sviluppatori)


