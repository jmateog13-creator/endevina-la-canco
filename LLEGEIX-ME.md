# 🎵 Endevina la Cançó

Concurs tipus PlayQuiz / QuizManía per a classe: sona un tros de la cançó, surten les opcions i es revela el videoclip.

## Obrir

Doble clic a **`Obrir Endevina la Cançó.command`**. S'obre el navegador a `http://localhost:8765`.
Deixa oberta la finestra del Terminal mentre jugues. Si aquell port està ocupat, agafa el següent lliure (8766, 8767…): **l'adreça bona sempre surt escrita al Terminal**.
El primer cop, si el macOS no et deixa obrir-lo: clic dret → Obrir.

> Ha d'anar pel servidor: si obres `index.html` directament, YouTube no reprodueix i no es pot buscar ni desar.

## Crear un quiz

1. **＋ Crear un quiz** → posa-li nom.
2. Enganxa la llista, una cançó per línia: `Artista - Cançó`.
   - `@1:05` al final tria on comença el tros.
   - Un enllaç de YouTube a la línia força aquell vídeo.
3. **Afegir i buscar a YouTube**: busca cada cançó i descarta els vídeos que no es poden incrustar.
4. Revisa cada fila: pots canviar el vídeo al desplegable i, prement la miniatura, **triar el segon exacte** on comença el tros.
5. Ajustos: què s'ha d'endevinar (artista / cançó / totes dues), durada del tros (màx. 15 s), temps per respondre al mòbil, nre. d'opcions, ordre aleatori.
6. **💾 Desar**. Els quizzes queden a la carpeta `quizzes/` com a `.json` (amb **Exportar** / **Importar** els passes a un altre ordinador).

Les opcions falses surten de les altres cançons del mateix quiz. Si n'hi ha poques o es repeteix artista, afegeix noms a «Noms extra per a les opcions falses».

## Jugar

El primer que veus en obrir la web és **Com hi jugareu?**: tria el mode i la web se'l recorda per a la propera. També el pots canviar a l'editor, al costat del botó **▶ Jugar**.

### 📺 Presentació
Tot a la pantalla gran. La classe contesta en veu alta i tu marques l'opció.

| Tecla | Acció |
|---|---|
| Espai | Escoltar → Revelar → Següent |
| 1–4 / A–D | Marcar l'opció que tria la classe |
| R | Repetir el tros |
| → | Següent ronda |

En acabar el tros la música es fon i es pausa; en triar o revelar, apareix el videoclip i sona com a màxim 15 s més. Al final surten els encerts i la llista amb les solucions.

### 📱 Amb mòbils (tipus Kahoot)
1. La pantalla gran mostra una adreça (ex. `192.168.1.40:8765/movil`), un **codi de 4 números** i un **QR**.
2. Els alumnes entren des del mòbil, posen el codi i el seu nom i apareixen a la pantalla.
3. **Començar**: a cada ronda sona el tros i les opcions surten als mòbils.
4. Es revela sola quan tothom ha respost o s'acaba el temps (o prems **Revelar**).
5. Punts: de 500 a 1000 per encert, més com més ràpid. Després de cada ronda, classificació; al final, podi.

### Passar l'enllaç als alumnes (Moodle, classroom, xat…)

A la pantalla de la sala surt l'adreça amb el **nom del portàtil**, per exemple
`http://el-teu-portatil.local:8767/movil`, i un botó **⧉ Copiar l'enllaç**.

Aquest enllaç és el bo per penjar al Moodle perquè **no canvia**: el nom del Mac és sempre el mateix,
encara que la wifi li doni una IP diferent cada dia. Perquè el port tampoc canviï, obre el servidor així:

```bash
python3 servidor.py --port 8767
```

Qui obre l'enllaç **no ha d'escriure el codi**: si només hi ha una partida oberta, la pàgina el posa sola
i només demana el nom. El codi i el QR segueixen sent-hi per si algú entra a mà.

Funciona igual des del mòbil que des del portàtil: la pàgina s'adapta a la pantalla.

Si el nom `.local` no funciona a la xarxa del centre (algunes el bloquegen), fes servir l'adreça per IP
que surt al Terminal; aquesta sí que pot canviar de dia en dia.

**Requisits:** els alumnes han d'estar a la **mateixa wifi** que l'ordinador, i el servidor ha d'estar obert. Si el macOS pregunta si el Python pot acceptar connexions entrants, digues que **sí**.
Si no connecten, és probable que la wifi del centre aïlli els dispositius: prova amb el punt d'accés del teu mòbil.

Des de la xarxa només es pot obrir la pàgina del mòbil: l'editor i els teus quizzes només es veuen des del teu ordinador.

## Sense spoilers
- El vídeo està tapat fins a revelar, i la tapa torna a l'instant en passar de ronda.
- Les targetes dels «Els meus quizzes» no mostren miniatures dels vídeos.
- A la pantalla de l'editor sí que es veuen els títols: no la projectis mentre prepares el quiz.
