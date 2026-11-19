Покладіть сюди СВОЇ файли (у пакеті їх немає):
  src.mp4        готове відео (аватар / TTS / голос), яке не треба різати
  voice_090.wav  зроби: python ../../../scripts/avatar_audio.py src.mp4 voice_090.wav --speed 0.9
  captions.json  зроби: python ../../../scripts/words_to_captions.py words.json captions.json
  music.mp3, pop.mp3, whoosh.mp3   ваша музика та звуки (з правами на використання)
  *.png (стікери з прозорістю), *.mp4 (перебивки-кліпи)
Скопіюйте creative.example.json -> creative.json і заповніть. Усі часи в конфізі в секундах ДЖЕРЕЛА.
Без music.mp3/pop.mp3/whoosh.mp3 шаблон НЕ відрендериться (Audio src обов'язковий): покладіть хоча б тихі/порожні файли.
