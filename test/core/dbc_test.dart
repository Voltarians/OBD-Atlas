import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/core/dbc.dart';

void main() {
  test('parses standard and CAN FD DBC messages', () {
    final document = DbcDocument.parse('test.dbc', '''
VERSION "Atlas"
BO_ 291 Standard: 8 ECU
 SG_ Speed : 0|16@1+ (0.01,0) [0|655.35] "km/h" Vector__XXX
BO_ 2147483939 ExtendedFD: 64 ECU
 SG_ Counter : 0|8@1+ (1,0) [0|255] "" Vector__XXX
''');
    expect(document.messages, 2);
    expect(document.signals, 2);
    expect(document.text.endsWith('\n'), isTrue);
  });

  test('rejects text without a DBC message', () {
    expect(() => DbcDocument.parse('bad.dbc', 'VERSION "bad"'), throwsA(isA<DbcFormatException>()));
  });
}
