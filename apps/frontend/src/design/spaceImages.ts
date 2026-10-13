import cepheus from '@/assets/space/cepheus-starfield.jpg';
import lacerta from '@/assets/space/lacerta-starfield.jpg';
import frontier from '@/assets/space/frontier-parallel.jpg';
import extreme from '@/assets/space/extreme-deep-field.jpg';
import ultra from '@/assets/space/ultra-deep-field.jpg';

// Full credits and original download URLs: assets/space/SOURCES.md.
export const spaceImages = [
  { src: cepheus, id: 'PIA12066', position: '50% 50%' },
  { src: frontier, id: 'GSFC_20171208_Archive_e000394', position: '50% 50%' },
  { src: lacerta, id: 'GSFC_20171208_Archive_e000084', position: '65% 45%' },
  { src: extreme, id: 'GSFC_20171208_Archive_e001651', position: '50% 50%' },
  { src: ultra, id: 'GSFC_20171208_Archive_e001061', position: '50% 50%' },
] as const;

export const imageHoldMs = 72000;
export const imageFadeMs = 24000;
