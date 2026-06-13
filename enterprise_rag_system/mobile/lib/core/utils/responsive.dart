import 'package:flutter/widgets.dart';

class Responsive {
  const Responsive._();

  static bool isWide(BuildContext context) {
    return MediaQuery.sizeOf(context).width >= 720;
  }

  static int gridColumns(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    if (width >= 1000) {
      return 4;
    }
    if (width >= 640) {
      return 2;
    }
    return 1;
  }
}
