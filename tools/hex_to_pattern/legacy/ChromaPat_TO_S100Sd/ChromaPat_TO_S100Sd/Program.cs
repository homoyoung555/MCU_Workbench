using System;
using System.Collections.Generic;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;

namespace ChromaPat_TO_S100Sd
{
    class Program
    {
        public static string ChromaPatPath = @"D:\01_Work\CP_Map_Change\";  //Stil文件路径
        public static string S100SdPath = @"D:\01_Work\CP_Map_Change\";  //Stil文件路径
        public static int cyc_count = 0;
        static void Main(string[] args)
        {
            DirectoryInfo root = new DirectoryInfo(ChromaPatPath);
            FileInfo[] thefileInfo = root.GetFiles("*.pat");

            foreach (FileInfo NextFile in thefileInfo)
            {
                string strFileName = NextFile.Name.Substring(0, NextFile.Name.IndexOf(".pat"));//获取新生成的pat文件名
                Console.WriteLine(strFileName);

                if (PatToSd(NextFile.FullName, strFileName))
                    Console.WriteLine("解析成功");
                else
                    Console.WriteLine("解析失败");
            }
            Console.ReadKey();
        }

        static public bool PatToSd(string patFileName, string sdFileName)
        {
            bool bSuccess = true;
            StreamReader sr = new StreamReader(patFileName, Encoding.Default);
            StreamWriter sw = new StreamWriter(S100SdPath + sdFileName + ".sd");

            string line;
            bool startFlag = false;
            while ((line = sr.ReadLine()) != null)
            {
                line = line.TrimStart();

                if (line.Contains("HEADER"))
                {
                    sw.WriteLine();
                    sw.WriteLine("HEAD[PIN_NAME]:");
                    startFlag = true;
                    continue;
                }
                if (startFlag)
                {
                    if (line.Contains("PATTERN"))
                    {
                        sw.WriteLine("END_HEAD;");
                        sw.WriteLine("@@PATTERN_DEFINE");
                        sw.WriteLine();
                        startFlag = false;
                        continue;
                    }
                    sw.WriteLine(line);
                }

                if (line.Contains("*") || line.Contains("//"))
                {
                    if (line.Contains("TS"))
                    {
                        sw.WriteLine("START:" + line.Substring(1, line.LastIndexOf('*') - 1) + ";");
                    }
                    else if (line.Contains("STOP"))
                    {
                        sw.WriteLine("END:" + line.Substring(1, line.LastIndexOf('*') - 1) + ";");
                        sw.WriteLine("@@END_PATTERN_DEFINE");
                    }
                    else if (line.Contains("RPT "))
                    {
                        //sw.WriteLine(line.Substring(1, line.LastIndexOf('*') - 1) + ";" + line.Substring(line.IndexOf("RPT")));
                        sw.WriteLine("      " + line.Replace("*", "").Insert(line.IndexOf("RPT") - 2, ";"));
                    }
                    else
                    {
                        sw.WriteLine("      " + line.Replace("*", ""));
                    }
                }

            }

            sr.Close();
            sw.Close();
            return bSuccess;
        }


    }
}
