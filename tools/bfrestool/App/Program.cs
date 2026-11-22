using System;
using System.IO;
using System.Linq;
using BfresLibrary;

class Program {
    static int Main(string[] args) {
        var cmd = args[0];
        if (cmd == "info") {
            var rf = new ResFile(args[1]);
            Console.WriteLine($"version {rf.VersionMajor}.{rf.VersionMajor2}.{rf.VersionMinor}.{rf.VersionMinor2} models {rf.Models.Count} skel {rf.SkeletalAnims.Count}");
            foreach (var a in rf.SkeletalAnims.Values.Take(5))
                Console.WriteLine($"  {a.Name} frames={a.FrameCount} bones={a.BoneAnims.Count}");
            return 0;
        }
        if (cmd == "resave") {
            var rf = new ResFile(args[1]);
            rf.Save(args[2]);
            return 0;
        }
        Console.Error.WriteLine("unknown cmd");
        return 1;
    }
}
