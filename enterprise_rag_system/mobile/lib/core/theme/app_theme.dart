import 'package:flutter/material.dart';

class AppTheme {
  const AppTheme._();

  static const Color _primary = Color(0xFF2563EB);
  static const Color _surface = Color(0xFFF8FAFC);
  static const Color _border = Color(0xFFE2E8F0);
  static const Color _text = Color(0xFF0F172A);
  static const Color _muted = Color(0xFF64748B);
  static const Color _darkSurface = Color(0xFF020617);
  static const Color _darkCard = Color(0xFF0F172A);
  static const Color _darkBorder = Color(0xFF24324A);

  static ThemeData get lightTheme {
    final colorScheme = ColorScheme.fromSeed(
      seedColor: _primary,
      brightness: Brightness.light,
      surface: _surface,
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: colorScheme,
      scaffoldBackgroundColor: _surface,
      dividerColor: _border,
      cardColor: Colors.white,
      appBarTheme: const AppBarTheme(
        centerTitle: false,
        elevation: 0,
        backgroundColor: Colors.white,
        foregroundColor: _text,
        surfaceTintColor: Colors.transparent,
        titleTextStyle: TextStyle(
          color: _text,
          fontSize: 19,
          fontWeight: FontWeight.w800,
        ),
      ),
      inputDecorationTheme: OutlineInputBorderTheme.lightInputDecorationTheme,
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(48, 48),
          textStyle: const TextStyle(fontWeight: FontWeight.w800),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(48, 46),
          foregroundColor: _text,
          side: const BorderSide(color: _border),
          textStyle: const TextStyle(fontWeight: FontWeight.w800),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
      ),
      textTheme: const TextTheme(
        headlineSmall: TextStyle(fontSize: 24, height: 1.16, color: _text),
        titleLarge: TextStyle(fontSize: 21, height: 1.22, color: _text),
        titleMedium: TextStyle(fontSize: 17, height: 1.28, color: _text),
        titleSmall: TextStyle(fontSize: 15, height: 1.3, color: _text),
        bodyLarge: TextStyle(fontSize: 16, height: 1.46, color: _text),
        bodyMedium: TextStyle(fontSize: 14, height: 1.42, color: _text),
        bodySmall: TextStyle(fontSize: 12.5, height: 1.35, color: _muted),
        labelLarge: TextStyle(fontSize: 14, height: 1.2, color: _text),
        labelMedium: TextStyle(fontSize: 12.5, height: 1.2, color: _text),
      ),
    );
  }

  static ThemeData get darkTheme {
    final colorScheme = ColorScheme.fromSeed(
      seedColor: _primary,
      brightness: Brightness.dark,
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: colorScheme,
      scaffoldBackgroundColor: _darkSurface,
      dividerColor: _darkBorder,
      cardColor: _darkCard,
      appBarTheme: const AppBarTheme(
        centerTitle: false,
        elevation: 0,
        backgroundColor: _darkSurface,
        foregroundColor: Color(0xFFF8FAFC),
        surfaceTintColor: Colors.transparent,
        titleTextStyle: TextStyle(
          color: Color(0xFFF8FAFC),
          fontSize: 19,
          fontWeight: FontWeight.w800,
        ),
      ),
      inputDecorationTheme: OutlineInputBorderTheme.darkInputDecorationTheme,
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(48, 48),
          textStyle: const TextStyle(fontWeight: FontWeight.w800),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(48, 46),
          textStyle: const TextStyle(fontWeight: FontWeight.w800),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
      ),
    );
  }
}

class OutlineInputBorderTheme {
  const OutlineInputBorderTheme._();

  static InputDecorationTheme get lightInputDecorationTheme {
    final border = OutlineInputBorder(
      borderRadius: BorderRadius.circular(16),
      borderSide: const BorderSide(color: AppTheme._border),
    );

    return InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      hintStyle: const TextStyle(color: Color(0xFF64748B)),
      labelStyle: const TextStyle(color: Color(0xFF475569)),
      prefixIconColor: const Color(0xFF64748B),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      enabledBorder: border,
      focusedBorder: border.copyWith(
        borderSide: const BorderSide(color: AppTheme._primary, width: 1.4),
      ),
      errorBorder: border.copyWith(
        borderSide: const BorderSide(color: Color(0xFFDC2626), width: 1.2),
      ),
      border: border,
    );
  }

  static InputDecorationTheme get darkInputDecorationTheme {
    final border = OutlineInputBorder(
      borderRadius: BorderRadius.circular(16),
      borderSide: const BorderSide(color: AppTheme._darkBorder),
    );

    return InputDecorationTheme(
      filled: true,
      fillColor: const Color(0xFF111827),
      hintStyle: const TextStyle(color: Color(0xFF94A3B8)),
      labelStyle: const TextStyle(color: Color(0xFFCBD5E1)),
      prefixIconColor: const Color(0xFF94A3B8),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      enabledBorder: border,
      focusedBorder: border.copyWith(
        borderSide: const BorderSide(color: AppTheme._primary, width: 1.4),
      ),
      border: border,
    );
  }
}
