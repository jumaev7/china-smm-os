import React, { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { Redirect } from 'expo-router';

import { useAuth } from '@/auth/AuthContext';
import { Screen } from '@/components/Screen';
import { useTheme } from '@/hooks/useTheme';
import { AppError, userFacingMessage } from '@/utils/errors';

export default function LoginScreen() {
  const colors = useTheme();
  const { status, login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status === 'authenticated') {
    return <Redirect href="/(tabs)/today" />;
  }

  const onSubmit = async () => {
    setError(null);
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      // Never log password.
    } catch (err) {
      if (err instanceof AppError && err.status === 401) {
        setError('Invalid credentials');
      } else if (err instanceof AppError && err.kind === 'network') {
        setError('Network error — check connection and API URL');
      } else if (err instanceof AppError && err.kind === 'server') {
        setError('Server error — try again shortly');
      } else {
        setError(userFacingMessage(err));
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Screen
      variant="fullscreen"
      style={{ backgroundColor: colors.bg }}
      testID="login-screen"
    >
      <KeyboardAvoidingView
        style={styles.root}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <View style={styles.inner}>
          <Text style={[styles.brand, { color: colors.accent }]}>
            China SMM OS
          </Text>
          <Text style={[styles.title, { color: colors.text }]}>Operator</Text>
          <Text style={[styles.sub, { color: colors.textMuted }]}>
            Read-only mobile control — Phase 2
          </Text>

          <TextInput
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="email-address"
            placeholder="Email"
            placeholderTextColor={colors.textMuted}
            value={email}
            onChangeText={setEmail}
            editable={!submitting}
            style={[
              styles.input,
              {
                backgroundColor: colors.inputBg,
                borderColor: colors.inputBorder,
                color: colors.text,
              },
            ]}
          />
          <TextInput
            placeholder="Password"
            placeholderTextColor={colors.textMuted}
            secureTextEntry
            value={password}
            onChangeText={setPassword}
            editable={!submitting}
            style={[
              styles.input,
              {
                backgroundColor: colors.inputBg,
                borderColor: colors.inputBorder,
                color: colors.text,
              },
            ]}
          />

          {error ? (
            <Text style={[styles.error, { color: colors.danger }]}>{error}</Text>
          ) : null}

          <Pressable
            onPress={onSubmit}
            disabled={submitting || !email || !password}
            style={[
              styles.btn,
              {
                backgroundColor: colors.accent,
                opacity: submitting || !email || !password ? 0.5 : 1,
              },
            ]}
          >
            {submitting ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.btnText}>Sign in</Text>
            )}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  inner: {
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 24,
    gap: 12,
  },
  brand: {
    fontSize: 14,
    fontWeight: '800',
    letterSpacing: 1.2,
    textTransform: 'uppercase',
  },
  title: {
    fontSize: 32,
    fontWeight: '800',
  },
  sub: {
    fontSize: 14,
    marginBottom: 12,
  },
  input: {
    borderWidth: 1,
    borderRadius: 10,
    minHeight: 48,
    paddingHorizontal: 14,
    fontSize: 16,
  },
  error: {
    fontSize: 14,
    fontWeight: '600',
  },
  btn: {
    marginTop: 8,
    minHeight: 48,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  btnText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
});
