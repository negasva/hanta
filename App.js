import { useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as MediaLibrary from 'expo-media-library';

const TOTAL = 90;
const INTERVAL_MS = 500;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export default function App() {
  const camera = useRef(null);
  const [camPerm, requestCam] = useCameraPermissions();
  const [libPerm, requestLib] = MediaLibrary.usePermissions({ writeOnly: true });
  const [status, setStatus] = useState('idle'); // idle | capturing | saving | done | error
  const [count, setCount] = useState(0);

  if (!camPerm || !libPerm) return <View style={styles.container} />;

  if (!camPerm.granted || !libPerm.granted) {
    return (
      <View style={styles.center}>
        <Text style={styles.title}>Permissions needed</Text>
        <Text style={styles.text}>Camera to take the photos, photo library to save them.</Text>
        <Pressable
          style={styles.button}
          onPress={async () => {
            await requestCam();
            await requestLib();
          }}
        >
          <Text style={styles.buttonText}>Grant access</Text>
        </Pressable>
        <StatusBar style="light" />
      </View>
    );
  }

  const start = async () => {
    setCount(0);
    setStatus('capturing');
    const uris = [];
    try {
      while (uris.length < TOTAL) {
        const t0 = Date.now();
        const photo = await camera.current.takePictureAsync({ quality: 0.9, skipProcessing: true });
        uris.push(photo.uri);
        setCount(uris.length);
        await sleep(Math.max(0, INTERVAL_MS - (Date.now() - t0)));
      }
      setStatus('saving');
      for (const uri of uris) await MediaLibrary.saveToLibraryAsync(uri);
      setStatus('done');
    } catch (e) {
      setStatus('error');
    }
  };

  const capturing = status === 'capturing';
  const progress = count / TOTAL;

  return (
    <View style={styles.container}>
      <CameraView ref={camera} style={StyleSheet.absoluteFill} facing="front" animateShutter={false} />
      <View style={styles.top}>
        <Text style={styles.instruction}>
          {status === 'idle' && 'Tap start, then slowly turn your head in every direction.'}
          {capturing && 'Keep turning: left, right, up, down, diagonals.'}
          {status === 'saving' && 'Saving to your photo library…'}
          {status === 'done' && `Done. ${TOTAL} photos saved to your iPhone.`}
          {status === 'error' && 'Something went wrong. Try again.'}
        </Text>
        <View style={styles.bar}>
          <View style={[styles.barFill, { width: `${progress * 100}%` }]} />
        </View>
        <Text style={styles.counter}>{count} / {TOTAL}</Text>
      </View>
      {!capturing && status !== 'saving' && (
        <Pressable style={[styles.button, styles.bottom]} onPress={start}>
          <Text style={styles.buttonText}>{status === 'idle' ? 'Start' : 'Start again'}</Text>
        </Pressable>
      )}
      <StatusBar style="light" />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000' },
  center: { flex: 1, backgroundColor: '#000', alignItems: 'center', justifyContent: 'center', padding: 24 },
  title: { color: '#fff', fontSize: 22, fontWeight: '600', marginBottom: 8 },
  text: { color: '#ccc', fontSize: 16, textAlign: 'center', marginBottom: 24 },
  top: { position: 'absolute', top: 70, left: 20, right: 20, alignItems: 'center' },
  instruction: { color: '#fff', fontSize: 18, fontWeight: '600', textAlign: 'center', marginBottom: 14 },
  bar: { width: '100%', height: 8, borderRadius: 4, backgroundColor: 'rgba(255,255,255,0.3)', overflow: 'hidden' },
  barFill: { height: '100%', backgroundColor: '#34c759' },
  counter: { color: '#fff', fontSize: 16, marginTop: 8 },
  button: { backgroundColor: '#fff', paddingVertical: 16, paddingHorizontal: 40, borderRadius: 30 },
  buttonText: { color: '#000', fontSize: 18, fontWeight: '600' },
  bottom: { position: 'absolute', bottom: 60, alignSelf: 'center' },
});
