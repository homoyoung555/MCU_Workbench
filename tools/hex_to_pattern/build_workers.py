"""Build isolated command-line adapters around the supplied C# conversion sources.

The adapter binds the output directory, supports old C# syntax, and gates the
Read_pat routine with a runtime data-readback switch. Waveform instructions remain intact.
Run at package-build time. End users do not need a C# compiler.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess

ROOT = Path(__file__).resolve().parent


def worker_name(source):
    return hashlib.sha256(source.encode('utf-8')).hexdigest()[:20] + '.exe'


def adapted_source(text):
    text, count = re.subn(r'(static\s+void\s+Read_pat\s*\([^)]*\)\s*\{)',
                         r'\1\n if (!WorkbenchHexEntry.Verify) return;', text)
    if count != 1:
        raise ValueError('Expected exactly one legacy Read_pat entry')
    text = re.sub(r'\bconst\s+string\s+StilPath_new\b', 'static string StilPath_new', text)
    def interpolation(match):
        arguments = []
        def field(part):
            expression = part.group(1)
            # The supplied SRAM sources use only identifiers, :X8, and a ternary.
            fmt = ':X8' if expression.endswith(':X8') else ''
            arguments.append(expression[:-3] if fmt else expression)
            return '{' + str(len(arguments) - 1) + fmt + '}'
        template = re.sub(r'(?<!\{)\{([^{}]+)\}(?!\})', field, match.group(1))
        return 'string.Format("' + template + '", ' + ', '.join(arguments) + ')'
    return re.sub(r'\$"([^"\n]*)"', interpolation, text)


BRIDGE = r'''
using System;
using System.IO;
using System.Linq;
using System.Reflection;
public static class WorkbenchHexEntry {
 public static bool Verify = true;
 public static int Main(string[] args) {
  try {
   if(args.Length != 4) throw new ArgumentException("Expected input, output directory, pattern name, verify");
   Verify = bool.Parse(args[3]);
   var flags=BindingFlags.Static|BindingFlags.Public|BindingFlags.NonPublic;
   var type=Assembly.GetExecutingAssembly().GetTypes().Single(t=>t.GetField("StilPath_new",flags)!=null);
   var output=Path.GetFullPath(args[1]); Directory.CreateDirectory(output);
   type.GetField("StilPath_new",flags).SetValue(null,output+Path.DirectorySeparatorChar);
   var method=type.GetMethod("Read",flags);
   if(method==null) throw new Exception("Legacy Read entry not found");
   var result=method.Invoke(null,new object[]{Path.GetFullPath(args[0]),args[2]});
   if(result is bool && !(bool)result) throw new Exception("Legacy converter returned false");
   return 0;
  } catch(Exception error) { Console.Error.WriteLine(error.GetBaseException().Message); return 1; }
 }
}
'''


def build():
    csc = Path(os.environ.get('WINDIR', 'C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    profiles = json.loads((ROOT/'profiles.json').read_text(encoding='utf-8'))
    from tempfile import TemporaryDirectory
    destination = ROOT/'workers'
    destination.mkdir(exist_ok=True)
    results = []
    with TemporaryDirectory() as temporary:
        stage = Path(temporary)
        (stage/'Entry.cs').write_text(BRIDGE, encoding='utf-8')
        for profile in profiles:
            if not profile['enabled']:
                continue
            source = profile['source']
            (stage/'Legacy.cs').write_text(adapted_source((ROOT/'legacy'/source).read_text(encoding='utf-8-sig')), encoding='utf-8')
            target = destination/worker_name(source)
            run = subprocess.run([str(csc), '/nologo', '/target:exe', '/main:WorkbenchHexEntry',
                                  '/out:'+str(target), str(stage/'Legacy.cs'), str(stage/'Entry.cs')],
                                 capture_output=True, timeout=90)
            message = run.stdout.decode('mbcs', errors='replace') + run.stderr.decode('mbcs', errors='replace')
            print(profile['id'], run.returncode, flush=True)
            if run.returncode:
                raise RuntimeError(message)
            results.append({'id': profile['id'], 'worker': target.name, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    (destination/'manifest.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    return results


if __name__ == '__main__':
    build()
