import {loadFont} from '@remotion/fonts';
import {staticFile} from 'remotion';

// Шрифти з папки агента (montage-agent/fonts), посилання кладе to_remotion.py
loadFont({family: 'Montserrat', url: staticFile('fonts/Montserrat-ExtraBold.ttf'), weight: '800'});
loadFont({family: 'Montserrat', url: staticFile('fonts/Montserrat-Bold.ttf'), weight: '700'});
loadFont({family: 'Montserrat', url: staticFile('fonts/Montserrat-Black.ttf'), weight: '900'});

export const FONT = 'Montserrat, sans-serif';
// Колір плашки субтитрів як у ролику apr 4.1 (Submagic); під інший ролик — інший
export const BOX_GREEN = '#325C3C';
export const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
