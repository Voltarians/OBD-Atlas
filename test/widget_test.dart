import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/main.dart';

void main() {
  testWidgets('OBD Atlas shell starts', (WidgetTester tester) async {
    await tester.pumpWidget(const ObdAtlasApp());
    await tester.pump();

    expect(find.text('OBD ATLAS'), findsOneWidget);
    expect(find.text('Vehicle'), findsWidgets);
    expect(find.text('Connect'), findsWidgets);
    expect(find.text('Capture'), findsWidgets);
    expect(find.text('Live'), findsWidgets);
    expect(find.text('Library'), findsWidgets);
  });
}
