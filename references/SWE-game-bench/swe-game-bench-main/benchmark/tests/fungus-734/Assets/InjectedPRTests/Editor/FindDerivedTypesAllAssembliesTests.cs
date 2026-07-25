#if UNITY_EDITOR
using NUnit.Framework;
using System;
using System.Linq;
using UnityEngine;
using Fungus.EditorUtils;

namespace InjectedPR
{
    public class InjectedDerivedType : InjectedBaseType
    {
    }

    public class FindDerivedTypesAllAssembliesTests
    {
        [Test]
        public void FindDerivedTypes_FindsDerivedInDifferentAssembly()
        {
            var baseType    = typeof(InjectedBaseType);
            var derivedType = typeof(InjectedDerivedType);

            var results = EditorExtensions.FindDerivedTypes(baseType, classOnly: true);
            Assert.That(results, Is.Not.Null);
            Assert.That(results.Contains(derivedType), Is.True,
                "Expected derived type from a different assembly to be discovered.");
        }
    }
}
#endif
