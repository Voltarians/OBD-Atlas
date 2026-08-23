import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/main.dart';

void main() {
  testWidgets('OBD Atlas opens in passive research mode', (tester) async {
    await tester.pumpWidget(const ObdAtlasApp());

    expect(find.text('OBD Atlas 0.1'), findsOneWidget);
    expect(find.text('PASSIVE'), findsOneWidget);
    expect(find.text('Discovery'), findsOneWidget);
    expect(find.text('ECUs'), findsOneWidget);
    expect(find.text('Logging'), findsOneWidget);
  });
}
