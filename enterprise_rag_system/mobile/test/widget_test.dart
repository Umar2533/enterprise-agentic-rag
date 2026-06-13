import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:mobile/app.dart';

void main() {
  testWidgets('loads the enterprise RAG app shell', (tester) async {
    await tester.pumpWidget(const EnterpriseRagApp());

    expect(find.byType(CircularProgressIndicator), findsWidgets);
  });
}
